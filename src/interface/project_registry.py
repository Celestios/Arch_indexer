"""Dynamic multi-project registry and database pool for Arch MCP daemon.

Manages isolated DuckDB connections and repositories per project workspace.
"""
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from db.connection import DbConnection
from db.repository import Repository
from utils.single_instance import get_global_arch_dir, PROJECTS_FILE_NAME


def normalize_path(path: Union[str, Path]) -> str:
    """Normalizes a filesystem path to forward slashes with drive letter normalized."""
    p = Path(path).resolve()
    return str(p).replace("\\", "/")


def find_project_root_with_db(start: Union[str, Path]) -> Optional[Path]:
    """Walks up the directory tree starting from `start` looking for `.arch/arch.db`.

    Returns the nearest ancestor Path containing `.arch/arch.db`, or None if not found.
    """
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


class ProjectRegistry:
    """Thread-safe registry of active workspace projects and their database connections."""

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
            is_user_home = (self.global_dir == user_home_arch)
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
    ) -> ProjectContext:
        """Initializes or retrieves an isolated project context.

        Raises FileNotFoundError if .arch/arch.db does not exist in the project directory
        or its ancestors.
        """
        root_path = Path(project_root).resolve()
        # Find root with db if subdirectory passed
        db_root = find_project_root_with_db(root_path)
        if db_root is not None:
            root_path = db_root
        norm_key = normalize_path(root_path)

        try:
            server_cfg = sys.modules.get("interface.server_config")
            if server_cfg is not None and hasattr(server_cfg, "get_db_path") and hasattr(server_cfg, "get_project_root"):
                if server_cfg.get_project_root() == root_path:
                    db_path = server_cfg.get_db_path()
                else:
                    db_path = root_path / ".arch" / "arch.db"
            else:
                db_path = root_path / ".arch" / "arch.db"
        except Exception:
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

            # Update persistence
            data = self._read_persisted_projects()
            projects = data.setdefault("projects", {})
            projects[norm_key] = {
                "name": root_path.name,
                "registered_at": projects.get(norm_key, {}).get("registered_at", now),
                "last_accessed": now,
            }
            data["active_project"] = norm_key
            self._write_persisted_projects(data)

            # Ensure watcher is running if watcher_manager is available
            if start_watcher:
                try:
                    from change_tracker.watcher_manager import WatcherManager
                    WatcherManager.get_instance().ensure_watcher(root_path)
                except Exception:
                    pass

            return ctx

    def resolve_project(
        self,
        project_root: Optional[Union[str, Path]] = None,
        filepath: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Resolves target project root using cascading heuristics:
        1. Explicit project_root argument (checks itself and walks up tree for .arch/arch.db)
        2. Explicit filepath ancestry (resolves relative paths and walks up tree)
        3. server_config explicit override
        4. Current working directory ancestry (walks up tree for .arch/arch.db)
        5. ARCH_PROJECT_ROOT environment variable (walks up tree)
        6. Currently loaded projects in memory with valid DB
        7. Persisted active_project in ~/.arch/projects.json (with valid DB)
        8. Fallback to server_config or CWD
        """
        with self._lock:
            # 1. Explicit project_root parameter: walk up from it for .arch/arch.db
            if project_root:
                db_root = find_project_root_with_db(project_root)
                if db_root is not None:
                    return db_root
                return Path(project_root).resolve()

            # 2. If filepath is provided, resolve against configured root or CWD, then walk up
            if filepath:
                p_file = Path(filepath)
                if not p_file.is_absolute():
                    base = None
                    server_cfg = sys.modules.get("interface.server_config")
                    if server_cfg is not None and hasattr(server_cfg, "_resolved") and "project_root" in server_cfg._resolved:
                        base = server_cfg._resolved["project_root"]
                    p_file = (Path(base) / p_file if base else (Path.cwd() / p_file)).resolve()
                db_root = find_project_root_with_db(p_file)
                if db_root is not None:
                    return db_root

                fp_str = normalize_path(p_file)
                # Check known active projects
                for norm_key, ctx in self._projects.items():
                    if (fp_str.lower().startswith(norm_key.lower() + "/") or fp_str.lower() == norm_key.lower()) and (ctx.root / ".arch" / "arch.db").exists():
                        return ctx.root

                # Check persisted projects
                persisted = self._read_persisted_projects().get("projects", {})
                for p_str in persisted.keys():
                    p = Path(p_str)
                    if (fp_str.lower().startswith(p_str.lower() + "/") or fp_str.lower() == p_str.lower()) and (p / ".arch" / "arch.db").exists():
                        return p

            # 3. Check server_config explicit override (e.g. test monkeypatch or CLI param)
            server_cfg = sys.modules.get("interface.server_config")
            if server_cfg is not None and hasattr(server_cfg, "_resolved") and "project_root" in server_cfg._resolved:
                cfg_root = server_cfg._resolved["project_root"]
                db_root = find_project_root_with_db(cfg_root)
                if db_root is not None:
                    return db_root
                return Path(cfg_root).resolve()

            # 4. Current working directory: check if CWD or any ancestor contains .arch/arch.db
            cwd_root = find_project_root_with_db(Path.cwd())
            if cwd_root is not None:
                return cwd_root

            # 5. Explicit environment override (only if valid db exists)
            if "ARCH_PROJECT_ROOT" in os.environ:
                env_val = os.environ["ARCH_PROJECT_ROOT"]
                db_root = find_project_root_with_db(env_val)
                if db_root is not None:
                    return db_root
                env_root = Path(env_val).resolve()
                if (env_root / ".arch" / "arch.db").exists():
                    return env_root

            # 6. Check loaded projects with valid DB
            valid_loaded = [ctx.root for ctx in self._projects.values() if (ctx.root / ".arch" / "arch.db").exists()]
            if len(valid_loaded) == 1:
                return valid_loaded[0]

            # 7. Persisted active_project or single persisted project (must have existing db)
            persisted_data = self._read_persisted_projects()
            active_proj = persisted_data.get("active_project")
            if active_proj:
                p = Path(active_proj)
                if (p / ".arch" / "arch.db").exists():
                    return p

            persisted_projects = persisted_data.get("projects", {})
            valid_persisted = [Path(p) for p in persisted_projects.keys() if (Path(p) / ".arch" / "arch.db").exists()]
            if len(valid_persisted) == 1:
                return valid_persisted[0]

            # 8. Fallback to server_config or CWD
            try:
                from interface.server_config import get_project_root
                cfg_root = get_project_root()
                db_root = find_project_root_with_db(cfg_root)
                if db_root is not None:
                    return db_root
                return cfg_root
            except Exception:
                return Path.cwd().resolve()

    def get_repository(
        self,
        project_root: Optional[Union[str, Path]] = None,
        filepath: Optional[Union[str, Path]] = None,
    ) -> Repository:
        """Resolves and returns the Repository for the given workspace context."""
        resolved_root = self.resolve_project(project_root=project_root, filepath=filepath)
        norm_key = normalize_path(resolved_root)

        with self._lock:
            if norm_key in self._projects:
                ctx = self._projects[norm_key]
                ctx.last_accessed = time.time()
                return ctx.repository

            ctx = self.register_project(resolved_root)
            return ctx.repository

    def list_projects(self) -> List[Dict[str, Any]]:
        """Returns metadata for all registered projects."""
        with self._lock:
            persisted = self._read_persisted_projects()
            active = persisted.get("active_project")
            proj_dict = persisted.get("projects", {})

            result = []
            for norm_key, info in proj_dict.items():
                p = Path(norm_key)
                is_active = (norm_key == active)
                is_loaded = norm_key in self._projects
                db_exists = (p / ".arch" / "arch.db").exists()
                result.append({
                    "root": norm_key,
                    "name": info.get("name", p.name),
                    "registered_at": info.get("registered_at"),
                    "last_accessed": info.get("last_accessed"),
                    "is_active": is_active,
                    "is_loaded": is_loaded,
                    "db_exists": db_exists,
                })
            return result

    def close_project(self, project_root: Union[str, Path]) -> bool:
        """Closes the connection pool for a specific project."""
        norm_key = normalize_path(project_root)
        with self._lock:
            if norm_key in self._projects:
                ctx = self._projects.pop(norm_key)
                try:
                    ctx.db_conn.close()
                except Exception:
                    pass
                return True
            return False

    def unregister_project(self, project_root: Union[str, Path]) -> bool:
        """Unregisters a workspace: closes DB connection, stops watcher, and removes from projects.json."""
        root_path = Path(project_root).resolve()
        norm_key = normalize_path(root_path)

        with self._lock:
            # 1. Close active db connection
            self.close_project(root_path)

            # 2. Stop watcher
            try:
                from change_tracker.watcher_manager import WatcherManager
                WatcherManager.get_instance().stop_watcher(root_path)
            except Exception:
                pass

            # 3. Remove from persistence
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
        """Closes all active database connections in the pool."""
        with self._lock:
            for ctx in self._projects.values():
                try:
                    ctx.db_conn.close()
                except Exception:
                    pass
            self._projects.clear()
