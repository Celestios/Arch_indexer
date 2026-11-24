"""Multi-project filesystem watcher manager for the Arch MCP daemon.

Maintains independent Watchdog observers and debounced re-indexing workers per workspace,
using a cross-process OS file lock (.arch/watcher.lock) for single-watcher election and
scoped DuckDB sessions so .arch/arch.db is never held open while idle.
"""
import atexit
from contextlib import contextmanager
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, ContextManager, Dict, List, Optional, Set, Tuple, Union

from change_tracker.tracker import calculate_sha256
from change_tracker.watcher import (
    _WATCHED_EXTENSIONS,
    _has_ffi_bridge_files,
    _resolve_package_root,
)
from db.connection import DbConnection
from db.repository import Repository
from engines.registry import LanguageRegistry
from engines.sync_pipeline import checkpoint_db, sync_workspace
from engines.treesitter import sync_file_to_db
from utils.exclusions import (
    is_excluded,
    is_included,
    load_exclude_patterns,
    load_include_dirs,
)

logger = logging.getLogger(__name__)

DEFAULT_SCIP_SCORE_THRESHOLD = 3500
DEFAULT_SCIP_MAX_AGE_SECONDS = 9000.0  # 2.5 hours
DEFAULT_SCIP_COALESCE_SECONDS = 10.0

_W_FILES = 5
_W_LINES = 1
_W_AST = 10
_W_STRUCTURAL = 25


def _count_file_lines(path: Path) -> Optional[int]:
    try:
        return len(path.read_bytes().splitlines())
    except OSError:
        return None


def _estimate_line_delta(path: Path, prev_lines: Optional[int]) -> Tuple[int, Optional[int]]:
    """Returns (estimated_changed_lines, current_line_count)."""
    curr_lines = _count_file_lines(path)
    if curr_lines is None:
        return 1, prev_lines
    if prev_lines is None:
        return 1, curr_lines
    return max(1, abs(curr_lines - prev_lines)), curr_lines


def normalize_path(path: Union[str, Path]) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


class _WatcherFileLock:
    """Non-blocking OS-enforced file lock (<project_root>/.arch/watcher.lock) for single-watcher election."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fp = None

    def acquire(self) -> bool:
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fp = open(self.lock_path, "a+", encoding="utf-8")
            fp.seek(0)
            if sys.platform == "win32":
                import msvcrt
                # Ensure at least 1 byte exists for msvcrt.locking
                if fp.tell() == 0 and not fp.read(1):
                    fp.write(" ")
                    fp.flush()
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            fp.seek(0)
            fp.truncate()
            fp.write(f"{os.getpid()}\n")
            fp.flush()
            self._fp = fp
            return True
        except OSError:
            try:
                fp.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return False

    def release(self) -> None:
        if self._fp is None:
            return
        fp = self._fp
        self._fp = None
        try:
            fp.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                fp.close()
            except Exception:
                pass


class ProjectWatcher:
    """Monitors a single project root for file changes with scoped DuckDB sessions and two-tiered re-indexing."""

    def __init__(
        self,
        project_root: Path,
        debounce: float = DEFAULT_SCIP_COALESCE_SECONDS,
        repository: Optional[Repository] = None,
        db_lock: Optional[threading.RLock] = None,
        db_session_factory: Optional[Callable[[], ContextManager[Repository]]] = None,
        scip_score_threshold: int = DEFAULT_SCIP_SCORE_THRESHOLD,
        scip_max_age: float = DEFAULT_SCIP_MAX_AGE_SECONDS,
    ):
        self.project_root = project_root.resolve()
        self.debounce = debounce
        self.scip_score_threshold = scip_score_threshold
        self.scip_max_age = scip_max_age
        self.arch_dir = self.project_root / ".arch"
        self.db_path = self.arch_dir / "arch.db"
        self._pending_state_path = self.arch_dir / "scip_pending.json"

        self._stop_event = threading.Event()
        self._last_trigger: float = 0.0
        self._first_trigger: float = 0.0
        self._pending: bool = False
        self._changed_files: Set[Path] = set()
        self._forced_dirty_rel: Set[str] = set()
        self._line_changes: Dict[str, int] = {}
        self._line_counts: Dict[str, int] = {}
        self._ast_changed: Set[str] = set()
        self._lock = threading.Lock()
        self._scip_run_lock = threading.Lock()
        self._db_lock: threading.RLock = db_lock if db_lock is not None else threading.RLock()

        self._observer = None
        self._worker_thread: Optional[threading.Thread] = None
        self._owns_db_conn: bool = repository is None
        self._db_conn: Optional[DbConnection] = None
        self._repository: Optional[Repository] = repository
        self._external_session_factory = db_session_factory
        self._file_lock = _WatcherFileLock(self.arch_dir / "watcher.lock")

    def _to_rel_posix(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def _compute_scip_score_locked(self) -> int:
        dirty_rel = {self._to_rel_posix(p) for p in self._changed_files} | self._forced_dirty_rel
        if not dirty_rel:
            return 0
        ffi_count = 1 if _has_ffi_bridge_files(list(dirty_rel)) else 0
        return (
            _W_FILES * len(dirty_rel)
            + _W_LINES * sum(self._line_changes.values())
            + _W_AST * len(self._ast_changed)
            + _W_STRUCTURAL * (len(self._forced_dirty_rel) + ffi_count)
        )

    def _save_pending_state_locked(self) -> None:
        """Atomically persists pending Tier-2 SCIP state to .arch/scip_pending.json."""
        try:
            if not self._changed_files and not self._forced_dirty_rel:
                if self._pending_state_path.exists():
                    self._pending_state_path.unlink()
                return
            self.arch_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "files": sorted({self._to_rel_posix(p) for p in self._changed_files}),
                "forced": sorted(self._forced_dirty_rel),
                "line_changes": dict(self._line_changes),
                "ast_changed": sorted(self._ast_changed),
                "first_dirty_wall": time.time() - max(0.0, time.monotonic() - self._first_trigger) if self._first_trigger else time.time(),
            }
            tmp_path = self._pending_state_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp_path, self._pending_state_path)
        except Exception:
            logger.debug("Failed to persist scip_pending.json for %s", self.project_root, exc_info=True)

    def _load_pending_state(self) -> None:
        """Restores persisted Tier-2 SCIP pending state after an abrupt restart/crash."""
        if not self._pending_state_path.exists():
            return
        try:
            data = json.loads(self._pending_state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Ignoring corrupt scip_pending.json in %s", self.project_root, exc_info=True)
            return
        files = data.get("files") or []
        forced = data.get("forced") or []
        if not files and not forced:
            return
        now_mono = time.monotonic()
        age = max(0.0, time.time() - float(data.get("first_dirty_wall", time.time())))
        with self._lock:
            for rel in files:
                self._changed_files.add(self.project_root / rel)
            self._forced_dirty_rel.update(forced)
            self._line_changes.update({str(k): int(v) for k, v in (data.get("line_changes") or {}).items()})
            self._ast_changed.update(data.get("ast_changed") or [])
            self._pending = True
            self._first_trigger = now_mono - age
            self._last_trigger = now_mono
        logger.info(
            "[Arch Watcher] Restored %d pending Tier-2 file(s) from previous session in %s",
            len(files) + len(forced),
            self.project_root.name,
        )

    @contextmanager
    def _db_session(self):
        """Yields Repository under scoped lock, closing DuckDB immediately on exit so idle locks never persist."""
        if self._external_session_factory is not None:
            with self._external_session_factory() as repo:
                yield repo
            return

        with self._db_lock:
            assert self._repository is not None
            try:
                yield self._repository
            finally:
                if self._db_conn is not None:
                    self._db_conn.close()

    def start(self) -> bool:
        if not self.db_path.exists():
            logger.warning("Watcher skipped for %s: database not found at %s", self.project_root, self.db_path)
            return False

        if not self._file_lock.acquire():
            logger.info(
                "[Arch Watcher] Another process already owns watcher for %s; skipping duplicate watcher.",
                self.project_root,
            )
            return False

        if self._repository is None:
            try:
                self._db_conn = DbConnection(self.db_path)
                self._repository = Repository(self._db_conn)
            except Exception:
                self._file_lock.release()
                logger.exception("Failed to initialize watcher DB wrapper for %s", self.project_root)
                return False

        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            self._file_lock.release()
            logger.warning("watchdog not installed. Skipping watcher for %s.", self.project_root)
            return False

        include_dirs = load_include_dirs(self.project_root)
        exclude_patterns = load_exclude_patterns(self.project_root)
        project_root = self.project_root
        watcher_self = self

        def _filter_path(raw_path: Optional[Union[str, bytes]]) -> Optional[Tuple[Path, str]]:
            if not raw_path:
                return None
            path = Path(os.fsdecode(raw_path))
            try:
                rel_posix = str(path.resolve().relative_to(project_root)).replace("\\", "/")
            except ValueError:
                return None

            if not rel_posix or any(part.startswith(".") for part in Path(rel_posix).parts):
                return None
            if is_excluded(rel_posix, exclude_patterns):
                return None
            if include_dirs and not is_included(rel_posix, include_dirs, exclude_patterns):
                return None
            if path.suffix.lower() not in _WATCHED_EXTENSIONS:
                return None
            return path, rel_posix

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return

                candidates: List[Tuple[Path, str]] = []
                for attr in ("src_path", "dest_path"):
                    raw = getattr(event, attr, None)
                    matched = _filter_path(raw)
                    if matched is not None:
                        candidates.append(matched)

                if not candidates:
                    return

                now_mono = time.monotonic()
                with watcher_self._lock:
                    if not watcher_self._pending:
                        watcher_self._first_trigger = now_mono
                    watcher_self._last_trigger = now_mono
                    watcher_self._pending = True
                    for path, rel_posix in candidates:
                        watcher_self._changed_files.add(path)
                        if path.exists() and path.is_file():
                            prev_lines = watcher_self._line_counts.get(rel_posix)
                            delta, curr_lines = _estimate_line_delta(path, prev_lines)
                            if curr_lines is not None:
                                watcher_self._line_counts[rel_posix] = curr_lines
                            watcher_self._line_changes[rel_posix] = watcher_self._line_changes.get(rel_posix, 0) + delta

                if not watcher_self._repository:
                    with watcher_self._lock:
                        watcher_self._save_pending_state_locked()
                    return

                for path, rel_posix in candidates:
                    if path.exists() and path.is_file():
                        try:
                            with watcher_self._db_session() as repo:
                                prev_meta = repo.workspace.get_file(rel_posix)
                                prev_ast = prev_meta.get("ast_sha256", "") if prev_meta else ""
                                sync_file_to_db(repo, path, project_root=project_root)
                                curr_meta = repo.workspace.get_file(rel_posix)
                                curr_ast = curr_meta.get("ast_sha256", "") if curr_meta else ""
                            if not prev_ast or curr_ast != prev_ast:
                                with watcher_self._lock:
                                    watcher_self._ast_changed.add(rel_posix)
                        except Exception:
                            logger.exception("Tier-1 watcher AST sync failed for %s", rel_posix)
                    else:
                        try:
                            with watcher_self._db_session() as repo:
                                deps = repo.graph.get_dependent_files([rel_posix])
                                repo.delete_file(rel_posix)
                            with watcher_self._lock:
                                watcher_self._forced_dirty_rel.add(rel_posix)
                                watcher_self._line_counts.pop(rel_posix, None)
                                for dep_fp in deps or []:
                                    watcher_self._forced_dirty_rel.add(dep_fp)
                                    watcher_self._changed_files.add(project_root / dep_fp)
                        except Exception:
                            logger.exception("Tier-1 watcher delete cleanup failed for %s", rel_posix)

                with watcher_self._lock:
                    watcher_self._save_pending_state_locked()

        self._load_pending_state()

        try:
            self._observer = Observer()
            self._observer.schedule(Handler(), str(self.project_root), recursive=True)
            self._observer.start()
        except Exception:
            self._file_lock.release()
            logger.exception("Failed to start Watchdog observer for %s", self.project_root)
            return False

        self._worker_thread = threading.Thread(
            target=self._debounce_worker,
            name=f"WatcherWorker-{self.project_root.name}",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("[Arch Watcher] Started watching %s", self.project_root)
        return True

    def has_pending_scip(self) -> bool:
        with self._lock:
            return bool(self._changed_files or self._forced_dirty_rel) or self._pending_state_path.exists()

    def _should_trigger_scip_locked(self, now_mono: float) -> bool:
        if not self._pending or (not self._changed_files and not self._forced_dirty_rel):
            return False
        if (now_mono - self._first_trigger) >= self.scip_max_age:
            return True
        if (now_mono - self._last_trigger) < self.debounce:
            return False
        return self._compute_scip_score_locked() >= self.scip_score_threshold

    def _execute_scip_batch(self, batch: List[Path], forced_dirty: Set[str]) -> bool:
        """Runs SCIP under _scip_run_lock and clears processed items only after success."""
        if not batch and not forced_dirty:
            return False
        with self._scip_run_lock:
            self._run_scip_reindex(batch, forced_dirty)
        processed_paths = set(batch)
        processed_rels = {self._to_rel_posix(p) for p in batch} | set(forced_dirty)
        with self._lock:
            self._changed_files -= processed_paths
            self._forced_dirty_rel -= processed_rels
            for rel in processed_rels:
                self._line_changes.pop(rel, None)
                self._ast_changed.discard(rel)
            if self._changed_files or self._forced_dirty_rel:
                self._pending = True
                self._first_trigger = time.monotonic()
            else:
                self._pending = False
                self._first_trigger = 0.0
            self._save_pending_state_locked()
        return True

    def flush_pending(self) -> bool:
        """Synchronously flushes any pending Tier-2 SCIP changes if present."""
        if not self._changed_files and not self._forced_dirty_rel and self._pending_state_path.exists():
            self._load_pending_state()
        with self._lock:
            if not self._changed_files and not self._forced_dirty_rel:
                return False
            batch = list(self._changed_files)
            forced_dirty = set(self._forced_dirty_rel)
        return self._execute_scip_batch(batch, forced_dirty)

    def clear_pending_files(self, filepaths: Optional[Set[str]] = None) -> None:
        """Clears pending Tier-2 SCIP state after an explicit manual sync/update."""
        with self._lock:
            if filepaths is None:
                self._changed_files.clear()
                self._forced_dirty_rel.clear()
                self._line_changes.clear()
                self._ast_changed.clear()
                self._pending = False
                self._first_trigger = 0.0
            else:
                normed = {fp.replace("\\", "/") for fp in filepaths}
                self._changed_files = {p for p in self._changed_files if self._to_rel_posix(p) not in normed}
                self._forced_dirty_rel -= normed
                for rel in normed:
                    self._line_changes.pop(rel, None)
                    self._ast_changed.discard(rel)
                if not self._changed_files and not self._forced_dirty_rel:
                    self._pending = False
                    self._first_trigger = 0.0
            self._save_pending_state_locked()

    def _debounce_worker(self):
        while not self._stop_event.is_set():
            time.sleep(0.5)

            batch: List[Path] = []
            forced_dirty: Set[str] = set()
            with self._lock:
                if self._should_trigger_scip_locked(time.monotonic()):
                    batch = list(self._changed_files)
                    forced_dirty = set(self._forced_dirty_rel)

            if not batch and not forced_dirty:
                continue

            try:
                self._execute_scip_batch(batch, forced_dirty)
            except Exception:
                logger.exception("[Arch Watcher] Error updating %s", self.project_root.name)

    def _run_scip_reindex(self, batch: List[Path], forced_dirty: Optional[Set[str]] = None):
        if not self.db_path.exists() or not self._repository:
            return

        forced_set = forced_dirty or set()

        with self._db_session() as repo:
            db_files = repo.workspace.get_all_files_metadata()

        dirty_files: Set[str] = set(forced_set)
        path_by_rel: Dict[str, Path] = {}
        for p in batch:
            try:
                rel_fp = str(p.resolve().relative_to(self.project_root)).replace("\\", "/")
            except ValueError:
                rel_fp = str(p).replace("\\", "/")
            path_by_rel[rel_fp] = p

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
        for rel_fp in dirty_files:
            p = path_by_rel.get(rel_fp) or (self.project_root / rel_fp)
            lang = LanguageRegistry.detect_language(str(p))
            if not lang:
                continue
            pkg_root = _resolve_package_root(p, self.project_root, lang)
            package_targets.add((lang, pkg_root))

        has_ffi = _has_ffi_bridge_files(list(dirty_files))
        logger.info(
            "[Arch Watcher] Re-indexing %d file(s) in %s (%s)",
            len(dirty_files),
            self.project_root.name,
            ", ".join(sorted(lang for lang, _ in package_targets)) or "auto",
        )

        # Pass _db_session so DuckDB stays completely unlocked while scip_dart/rust-analyzer execute
        sync_res = sync_workspace(
            self._repository,
            self.project_root,
            dirty_files=dirty_files,
            run_ffi=has_ffi,
            package_targets=package_targets or None,
            session_factory=self._db_session,
        )

        if sync_res["indexed_languages"]:
            from auditor.analyzer import Auditor
            with self._db_session() as repo:
                auditor = Auditor(repo, self.project_root)
                if len(dirty_files) == 1:
                    auditor.run_audit(filepath_filter=next(iter(dirty_files)))
                else:
                    try:
                        common_prefix = os.path.commonpath(list(dirty_files)).replace("\\", "/")
                    except ValueError:
                        common_prefix = ""
                    if common_prefix and common_prefix != ".":
                        auditor.run_audit(filepath_filter=common_prefix)
                    else:
                        auditor.run_audit()
                checkpoint_db(repo)

    def stop(self):
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
        if self._owns_db_conn and self._db_conn is not None:
            try:
                self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None
        self._repository = None
        self._file_lock.release()


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

    def ensure_watcher(
        self,
        project_root: Union[str, Path],
        debounce: float = DEFAULT_SCIP_COALESCE_SECONDS,
        repository: Optional[Repository] = None,
        db_lock: Optional[threading.RLock] = None,
        db_session_factory: Optional[Callable[[], ContextManager[Repository]]] = None,
        scip_score_threshold: int = DEFAULT_SCIP_SCORE_THRESHOLD,
        scip_max_age: float = DEFAULT_SCIP_MAX_AGE_SECONDS,
    ) -> bool:
        root_path = Path(project_root).resolve()
        norm_key = normalize_path(root_path)

        with self._lock:
            if norm_key in self._watchers:
                return True

            watcher = ProjectWatcher(
                root_path,
                debounce=debounce,
                repository=repository,
                db_lock=db_lock,
                db_session_factory=db_session_factory,
                scip_score_threshold=scip_score_threshold,
                scip_max_age=scip_max_age,
            )
            if watcher.start():
                self._watchers[norm_key] = watcher
                return True
            return False

    def flush_pending(self, project_root: Union[str, Path]) -> bool:
        """Flushes pending Tier-2 SCIP changes for a watched project root if any exist."""
        norm_key = normalize_path(project_root)
        with self._lock:
            watcher = self._watchers.get(norm_key)
        if watcher is not None:
            return watcher.flush_pending()
        return False

    def clear_pending(self, project_root: Union[str, Path], filepaths: Optional[Set[str]] = None) -> None:
        """Clears pending Tier-2 SCIP state for a watched project root after explicit sync."""
        norm_key = normalize_path(project_root)
        with self._lock:
            watcher = self._watchers.get(norm_key)
        if watcher is not None:
            watcher.clear_pending_files(filepaths)

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
        with self._lock:
            for watcher in self._watchers.values():
                watcher.stop()
            self._watchers.clear()


atexit.register(lambda: WatcherManager.get_instance().stop_all())
