"""Dynamic multi-project registry and scoped DuckDB session manager for Arch MCP daemon.

Manages isolated ProjectContexts with reentrant scoped DuckDB sessions so .arch/arch.db
is released and checkpointed immediately when idle, allowing concurrent CLI & multi-client access.
"""
from contextlib import contextmanager
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from db.connection import DbConnection
from db.repository import Repository
from utils.single_instance import PROJECTS_FILE_NAME, get_global_arch_dir

logger = logging.getLogger(__name__)


def normalize_path(path: Union[str, Path]) -> str:
    """Normalizes a filesystem path to forward slashes."""
    return str(Path(path).resolve()).replace("\\", "/")


def find_project_root_with_db(start: Union[str, Path]) -> Optional[Path]:
    """Walks up the directory tree starting from `start` looking for `.arch/arch.db`."""
    try:
        p = Path(start).resolve()
        cur = p if p.is_dir() else p.parent
        while True:
            if (cur / ".arch" / "arch.db").exists():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    except Exception:
        pass
    return None


@dataclass
class ProjectContext:
    root: Path
    db_conn: DbConnection
    repository: Repository
    last_accessed: float
    db_lock: threading.RLock = field(default_factory=threading.RLock)
    _session_depth: int = field(default=0, init=False, repr=False)

    @contextmanager
    def db_session(self):
        """
        Reentrant scoped DB session: acquires db_lock, reuses the open DuckDB connection across
        nested calls, and closes DuckDB on outermost exit to flush WAL and release OS file locks.
        """
        with self.db_lock:
            self._session_depth += 1
            try:
                yield self.repository
            finally:
                self._session_depth -= 1
                if self._session_depth == 0:
                    self.db_conn.close()


class ProjectRegistry:
    """Thread-safe registry of active workspace projects and their scoped database contexts."""

    _instance: Optional["ProjectRegistry"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, global_dir: Optional[Path] = None):
        self.global_dir = (global_dir or get_global_arch_dir()).resolve()
        self.projects_file = self.global_dir / PROJECTS_FILE_NAME
        self._projects: Dict[str, ProjectContext] = {}
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls, global_dir: Optional[Path] = None) -> "ProjectRegistry":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(global_dir=global_dir)
            return cls._instance

    @classmethod
    def reset_instance(cls):
        """Resets global singleton and closes all connections."""
        with cls._singleton_lock:
            if cls._instance is not None:
                cls._instance.close_all()
                cls._instance = None

    def _read_persisted_projects(self) -> Dict[str, Any]:
        if not self.projects_file.exists():
            return {"projects": {}, "active_project": None}
        try:
            data = json.loads(self.projects_file.read_text(encoding="utf-8"))
            projects = data.get("projects", {})
            pruned = False
            user_home_arch = (Path.home() / ".arch").resolve()
            is_user_home = self.global_dir == user_home_arch
            for p_str in list(projects.keys()):
                p = Path(p_str)
                p_lower = p_str.lower()
                is_temp_test = is_user_home and (
                    "pytest" in p_lower
                    or "tmp" in p.name.lower()
                    or "/appdata/local/temp" in p_lower
                    or "\\appdata\\local\\temp" in p_lower
                )
                if not p.exists() or not p.is_dir() or is_temp_test:
                    projects.pop(p_str, None)
                    pruned = True
            active = data.get("active_project")
            if active and (not Path(active).exists() or not Path(active).is_dir()):
                data["active_project"] = next(iter(projects.keys()), None)
                pruned = True
            if pruned:
                self._write_persisted_projects(data)
            return data
        except Exception:
            return {"projects": {}, "active_project": None}

    def _write_persisted_projects(self, data: Dict[str, Any]):
        try:
            self.global_dir.mkdir(parents=True, exist_ok=True)
            self.projects_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def register_project(
        self,
        project_root: Union[str, Path],
        start_watcher: bool = True,
        set_active: Optional[bool] = None,
    ) -> ProjectContext:
        """Initializes or retrieves a ProjectContext without opening a persistent DuckDB handle."""
        root_path = Path(project_root).resolve()
        db_root = find_project_root_with_db(root_path)
        if db_root is not None:
            root_path = db_root
        norm_key = normalize_path(root_path)
        db_path = root_path / ".arch" / "arch.db"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Arch database not found at {db_path}. Please run 'arch init' in '{root_path}' first."
            )

        with self._lock:
            now = time.time()
            if norm_key in self._projects:
                ctx = self._projects[norm_key]
                ctx.last_accessed = now
                if start_watcher:
                    try:
                        from change_tracker.watcher_manager import WatcherManager
                        WatcherManager.get_instance().ensure_watcher(
                            root_path,
                            repository=ctx.repository,
                            db_lock=ctx.db_lock,
                            db_session_factory=ctx.db_session,
                        )
                    except Exception:
                        logger.exception("Failed to ensure watcher for %s", root_path)
                return ctx

            conn = DbConnection(db_path)
            repo = Repository(conn)
            ctx = ProjectContext(
                root=root_path,
                db_conn=conn,
                repository=repo,
                last_accessed=now,
            )
            self._projects[norm_key] = ctx

            data = self._read_persisted_projects()
            projects = data.setdefault("projects", {})
            projects[norm_key] = {
                "name": root_path.name,
                "registered_at": projects.get(norm_key, {}).get("registered_at", now),
                "last_accessed": now,
            }
            if set_active is True:
                data["active_project"] = norm_key
            elif set_active is None:
                curr_active = data.get("active_project")
                if not curr_active or not (Path(curr_active) / ".arch" / "arch.db").exists():
                    data["active_project"] = norm_key
            self._write_persisted_projects(data)

            if start_watcher:
                try:
                    from change_tracker.watcher_manager import WatcherManager
                    WatcherManager.get_instance().ensure_watcher(
                        root_path,
                        repository=ctx.repository,
                        db_lock=ctx.db_lock,
                        db_session_factory=ctx.db_session,
                    )
                except Exception:
                    logger.exception("Failed to start watcher for %s", root_path)

            return ctx

    def set_active_project(self, project_root: Union[str, Path]) -> bool:
        """Sets the active project in global persisted metadata."""
        root_path = Path(project_root).resolve()
        db_root = find_project_root_with_db(root_path)
        if db_root is not None:
            root_path = db_root
        norm_key = normalize_path(root_path)
        with self._lock:
            data = self._read_persisted_projects()
            data["active_project"] = norm_key
            self._write_persisted_projects(data)
        return True

    def resolve_project(
        self,
        project_root: Optional[Union[str, Path]] = None,
        filepath: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Resolves target project root using explicit cascading heuristics."""
        with self._lock:
            if project_root:
                db_root = find_project_root_with_db(project_root)
                if db_root is not None:
                    return db_root
                return Path(project_root).resolve()

            if filepath:
                p_file = Path(filepath)
                if not p_file.is_absolute():
                    p_file = (Path.cwd() / p_file).resolve()
                db_root = find_project_root_with_db(p_file)
                if db_root is not None:
                    return db_root

                fp_str = normalize_path(p_file)
                for norm_key, ctx in self._projects.items():
                    if (
                        fp_str.lower().startswith(norm_key.lower() + "/")
                        or fp_str.lower() == norm_key.lower()
                    ) and (ctx.root / ".arch" / "arch.db").exists():
                        return ctx.root

                persisted = self._read_persisted_projects().get("projects", {})
                for p_str in persisted.keys():
                    p = Path(p_str)
                    if (
                        fp_str.lower().startswith(p_str.lower() + "/")
                        or fp_str.lower() == p_str.lower()
                    ) and (p / ".arch" / "arch.db").exists():
                        return p

            cwd_root = find_project_root_with_db(Path.cwd())
            if cwd_root is not None:
                return cwd_root

            if "ARCH_PROJECT_ROOT" in os.environ:
                env_val = os.environ["ARCH_PROJECT_ROOT"]
                db_root = find_project_root_with_db(env_val)
                if db_root is not None:
                    return db_root
                env_root = Path(env_val).resolve()
                if (env_root / ".arch" / "arch.db").exists():
                    return env_root

            valid_loaded = [
                ctx.root
                for ctx in self._projects.values()
                if (ctx.root / ".arch" / "arch.db").exists()
            ]
            if len(valid_loaded) == 1:
                return valid_loaded[0]

            persisted_data = self._read_persisted_projects()
            active_proj = persisted_data.get("active_project")
            if active_proj:
                p = Path(active_proj)
                if (p / ".arch" / "arch.db").exists():
                    return p

            persisted_projects = persisted_data.get("projects", {})
            valid_persisted = [
                Path(p)
                for p in persisted_projects.keys()
                if (Path(p) / ".arch" / "arch.db").exists()
            ]
            if len(valid_persisted) == 1:
                return valid_persisted[0]

            return Path.cwd().resolve()

    def get_context(
        self,
        project_root: Optional[Union[str, Path]] = None,
        filepath: Optional[Union[str, Path]] = None,
    ) -> ProjectContext:
        """Resolves and returns the ProjectContext (Repository + scoped db_session) for the workspace."""
        resolved_root = self.resolve_project(project_root=project_root, filepath=filepath)
        norm_key = normalize_path(resolved_root)

        with self._lock:
            if norm_key in self._projects:
                ctx = self._projects[norm_key]
                ctx.last_accessed = time.time()
                return ctx
            return self.register_project(resolved_root)

    def get_repository(
        self,
        project_root: Optional[Union[str, Path]] = None,
        filepath: Optional[Union[str, Path]] = None,
    ) -> Repository:
        """Resolves and returns the Repository for the given workspace context."""
        return self.get_context(project_root=project_root, filepath=filepath).repository

    def list_projects(self) -> List[Dict[str, Any]]:
        """Returns metadata for all registered projects."""
        with self._lock:
            persisted = self._read_persisted_projects()
            active = persisted.get("active_project")
            proj_dict = persisted.get("projects", {})

            result = []
            for norm_key, info in proj_dict.items():
                p = Path(norm_key)
                result.append({
                    "root": norm_key,
                    "name": info.get("name", p.name),
                    "registered_at": info.get("registered_at"),
                    "last_accessed": info.get("last_accessed"),
                    "is_active": norm_key == active,
                    "is_loaded": norm_key in self._projects,
                    "db_exists": (p / ".arch" / "arch.db").exists(),
                })
            return result

    def close_project(self, project_root: Union[str, Path]) -> bool:
        """Stops watcher and closes the connection pool for a specific project."""
        norm_key = normalize_path(project_root)
        with self._lock:
            try:
                from change_tracker.watcher_manager import WatcherManager
                WatcherManager.get_instance().stop_watcher(project_root)
            except Exception:
                pass
            if norm_key in self._projects:
                ctx = self._projects.pop(norm_key)
                with ctx.db_lock:
                    try:
                        ctx.db_conn.close()
                    except Exception:
                        pass
                return True
            return False

    def unregister_project(self, project_root: Union[str, Path]) -> bool:
        """Unregisters a workspace: stops watcher, closes DB connection, and removes from projects.json."""
        root_path = Path(project_root).resolve()
        norm_key = normalize_path(root_path)

        with self._lock:
            self.close_project(root_path)

            data = self._read_persisted_projects()
            projects = data.get("projects", {})
            removed = False
            if norm_key in projects:
                projects.pop(norm_key, None)
                removed = True

            if data.get("active_project") == norm_key:
                data["active_project"] = next(iter(projects.keys()), None)
                removed = True

            if removed:
                self._write_persisted_projects(data)

            return removed

    def close_all(self):
        """Stops all watchers and closes all active database connections."""
        with self._lock:
            try:
                from change_tracker.watcher_manager import WatcherManager
                WatcherManager.get_instance().stop_all()
            except Exception:
                pass
            for ctx in self._projects.values():
                with ctx.db_lock:
                    try:
                        ctx.db_conn.close()
                    except Exception:
                        pass
            self._projects.clear()
