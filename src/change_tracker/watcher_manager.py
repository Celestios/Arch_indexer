"""Multi-project filesystem watcher manager for the Arch MCP daemon.

Maintains independent Watchdog observers and debounced re-indexing workers per workspace.
"""
import atexit
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Set, Union

from change_tracker.tracker import calculate_sha256
from change_tracker.watcher import (
    _FFI_BRIDGE_INDICATORS,
    _WATCHED_EXTENSIONS,
    _has_ffi_bridge_files,
    _resolve_package_root,
)
from db.connection import DbConnection
from db.repository import Repository
from engines.registry import LanguageRegistry
from engines.sync_pipeline import sync_workspace
from engines.treesitter import sync_file_to_db
from utils.exclusions import load_include_dirs


def normalize_path(path: Union[str, Path]) -> str:
    p = Path(path).resolve()
    return str(p).replace("\\", "/")


class ProjectWatcher:
    """Monitors a single project root for file changes with two-tiered re-indexing."""

    def __init__(self, project_root: Path, debounce: float = 3.0):
        self.project_root = project_root.resolve()
        self.debounce = debounce
        self.arch_dir = self.project_root / ".arch"
        self.db_path = self.arch_dir / "arch.db"

        self._stop_event = threading.Event()
        self._last_trigger: float = 0.0
        self._pending: bool = False
        self._changed_files: Set[Path] = set()
        self._lock = threading.Lock()
        self._db_lock = threading.Lock()

        self._observer = None
        self._worker_thread: Optional[threading.Thread] = None
        self._db_conn: Optional[DbConnection] = None
        self._repository: Optional[Repository] = None

    def start(self) -> bool:
        if not self.db_path.exists():
            return False

        try:
            self._db_conn = DbConnection(self.db_path)
            self._repository = Repository(self._db_conn)
        except Exception:
            return False

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            print("[Arch Watcher] watchdog not installed. Skipping watcher.", file=sys.stderr)
            return False

        include_dirs = load_include_dirs(self.project_root)
        project_root = self.project_root
        watcher_self = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return

                path = Path(os.fsdecode(event.src_path))
                try:
                    rel_parts = path.relative_to(project_root).parts
                except ValueError:
                    return

                # Exclude dotfiles, build/target/node_modules/venv
                if any(part.startswith(".") for part in rel_parts):
                    return
                if any(part in ("venv", ".venv", "bin", "build", "target", "node_modules") for part in rel_parts):
                    return

                if include_dirs and not any(part in include_dirs for part in rel_parts):
                    return

                if path.suffix.lower() not in _WATCHED_EXTENSIONS:
                    return

                with watcher_self._lock:
                    watcher_self._last_trigger = time.monotonic()
                    watcher_self._pending = True
                    watcher_self._changed_files.add(path)

                # Tier 1: Fast Tree-sitter AST sync (< 2ms)
                if path.exists() and path.is_file() and watcher_self._repository:
                    try:
                        with watcher_self._db_lock:
                            sync_file_to_db(watcher_self._repository, path, project_root=project_root)
                    except Exception:
                        pass

        self._observer = Observer()
        self._observer.schedule(Handler(), str(self.project_root), recursive=True)
        self._observer.start()

        self._worker_thread = threading.Thread(
            target=self._debounce_worker,
            name=f"WatcherWorker-{self.project_root.name}",
            daemon=True,
        )
        self._worker_thread.start()
        return True

    def _debounce_worker(self):
        """Worker loop for Tier 2 debounced SCIP re-indexing and auditing."""
        while not self._stop_event.is_set():
            time.sleep(0.5)

            batch = []
            with self._lock:
                if self._pending and (time.monotonic() - self._last_trigger) >= self.debounce:
                    self._pending = False
                    batch = list(self._changed_files)
                    self._changed_files.clear()

            if not batch:
                continue

            try:
                self._run_scip_reindex(batch)
            except Exception as e:
                print(f"[Arch Watcher] Error updating {self.project_root.name}: {e}", file=sys.stderr)

    def _run_scip_reindex(self, batch: list):
        if not self.db_path.exists() or not self._repository:
            return

        repository = self._repository

        with self._db_lock:
            db_files = repository.workspace.get_all_files_metadata()
        dirty_files: Set[str] = set()
        for p in batch:
            try:
                rel_fp = str(p.resolve().relative_to(self.project_root)).replace("\\", "/")
            except ValueError:
                rel_fp = str(p).replace("\\", "/")

            if not p.exists():
                dirty_files.add(rel_fp)
                continue

            curr_hash = calculate_sha256(p)
            db_hash = db_files.get(rel_fp, {}).get("sha256", "")
            if curr_hash != db_hash:
                dirty_files.add(rel_fp)

        if not dirty_files:
            return

        package_targets = set()
        for p in batch:
            try:
                rel_fp = str(p.resolve().relative_to(self.project_root)).replace("\\", "/")
            except ValueError:
                rel_fp = str(p).replace("\\", "/")
            if rel_fp not in dirty_files:
                continue
            lang = LanguageRegistry.detect_language(str(p))
            if not lang:
                continue
            pkg_root = _resolve_package_root(p, self.project_root, lang)
            package_targets.add((lang, pkg_root))

        has_ffi = _has_ffi_bridge_files(batch)
        with self._db_lock:
            sync_res = sync_workspace(
                repository,
                self.project_root,
                dirty_files=dirty_files,
                run_ffi=has_ffi,
                package_targets=package_targets or None,
            )

            if sync_res["indexed_languages"]:
                from auditor.analyzer import Auditor
                auditor = Auditor(repository, self.project_root)
                if len(dirty_files) == 1:
                    auditor.run_audit(filepath_filter=next(iter(dirty_files)))
                else:
                    try:
                        common_prefix = os.path.commonpath(list(dirty_files)).replace("\\", "/")
                        if common_prefix and common_prefix != ".":
                            auditor.run_audit(filepath_filter=common_prefix)
                        else:
                            for fp in dirty_files:
                                auditor.run_audit(filepath_filter=fp)
                    except Exception:
                        for fp in dirty_files:
                            auditor.run_audit(filepath_filter=fp)

    def stop(self):
        """Stops the observer, worker thread, and closes database connection."""
        self._stop_event.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)
            self._worker_thread = None
        if self._db_conn is not None:
            try:
                self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None
            self._repository = None


class WatcherManager:
    """Manages concurrent watchers across registered project roots."""

    _instance: Optional["WatcherManager"] = None
    _singleton_lock = threading.Lock()

    def __init__(self):
        self._watchers: Dict[str, ProjectWatcher] = {}
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "WatcherManager":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._singleton_lock:
            if cls._instance is not None:
                cls._instance.stop_all()
                cls._instance = None

    def ensure_watcher(self, project_root: Union[str, Path], debounce: float = 3.0) -> bool:
        """Starts a background watcher for the project root if not already watching."""
        root_path = Path(project_root).resolve()
        norm_key = normalize_path(root_path)

        with self._lock:
            if norm_key in self._watchers:
                return True

            watcher = ProjectWatcher(root_path, debounce=debounce)
            started = watcher.start()
            if started:
                self._watchers[norm_key] = watcher
                return True
            return False

    def stop_watcher(self, project_root: Union[str, Path]) -> bool:
        norm_key = normalize_path(project_root)
        with self._lock:
            if norm_key in self._watchers:
                watcher = self._watchers.pop(norm_key)
                watcher.stop()
                return True
            return False

    def is_watching(self, project_root: Union[str, Path]) -> bool:
        norm_key = normalize_path(project_root)
        with self._lock:
            return norm_key in self._watchers

    def stop_all(self):
        """Stops all active watchers on daemon termination."""
        with self._lock:
            for watcher in self._watchers.values():
                watcher.stop()
            self._watchers.clear()


atexit.register(lambda: WatcherManager.get_instance().stop_all())

