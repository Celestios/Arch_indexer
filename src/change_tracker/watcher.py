import os
import sys
import time
from pathlib import Path
from typing import Set

from db.connection import DbConnection
from db.repository import Repository
from engines.scip_wrapper import ScipWrapper
from auditor.analyzer import Auditor
from engines.ffi_linker import FfiLinker
from utils.exclusions import load_include_dirs, is_included

_WATCHED_EXTENSIONS = {".rs", ".dart"}

def start_watcher(project_root: Path, debounce: float = 3.0):
    """
    Watches the project root for file changes and triggers re-indexing and auditing.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError as e:
        raise ImportError("watchdog not installed. Run: pip install watchdog") from e

    project_root = project_root.resolve()
    arch_dir = project_root / ".arch"
    db_path = arch_dir / "arch.db"

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}. Please run 'arch init' first.", file=sys.stderr)
        return

    last_trigger: float = 0.0
    pending: bool = False
    changed_files: Set[Path] = set()

    include_dirs = load_include_dirs(project_root)

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            nonlocal last_trigger, pending
            if event.is_directory:
                return

            path = Path(os.fsdecode(event.src_path))

            # Check exclusions
            try:
                rel_parts = path.relative_to(project_root).parts
            except ValueError:
                return

            # Ignore dotfiles/directories, venvs, and build dirs
            if any(part.startswith(".") for part in rel_parts):
                return
            if any(part in ("venv", ".venv", "bin", "build", "target", "node_modules") for part in rel_parts):
                return

            # Filter by include_dirs if configured
            if include_dirs and not any(part in include_dirs for part in rel_parts):
                return

            if path.suffix.lower() not in _WATCHED_EXTENSIONS:
                return

            last_trigger = time.monotonic()
            pending = True
            changed_files.add(path)

    handler = Handler()
    observer = Observer()
    observer.schedule(handler, str(project_root), recursive=True)
    observer.start()

    print(f"[arch watch] Watching {project_root} - press Ctrl+C to stop")
    print(f"[arch watch] Debounce: {debounce}s")

    try:
        while True:
            time.sleep(0.5)
            if pending and (time.monotonic() - last_trigger) >= debounce:
                pending = False
                batch = list(changed_files)
                changed_files.clear()
                
                print(f"\n[arch watch] {len(batch)} file(s) changed. Re-indexing...")
                
                db_conn = DbConnection(db_path)
                repository = Repository(db_conn)
                
                try:
                    languages = ScipWrapper.detect_languages(project_root)
                    indexed_any = False
                    for lang in languages:
                        print(f"[arch watch] Running indexer for {lang}...")
                        index_path = ScipWrapper.run_indexer(project_root, lang)
                        if index_path:
                            parsed = ScipWrapper.parse_index(index_path, project_root)
                            ScipWrapper.ingest_index(repository, parsed, project_root=project_root)
                            indexed_any = True
                    
                    if indexed_any:
                        print("[arch watch] Re-indexing complete. Running compliance audit...")
                        auditor = Auditor(repository, project_root)
                        violations = auditor.run_audit()
                        if violations:
                            print(f"[arch watch] Found {len(violations)} violations:")
                            for v in violations:
                                print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} — {v['message']}")
                        else:
                            print("[arch watch] Audit complete. No violations found.")
                    else:
                        print("[arch watch] Re-indexing failed.")

                    # Re-run FFI bridge linking
                    try:
                        linker = FfiLinker(repository)
                        edges_created = linker.link_scip_bridges()
                        if edges_created:
                            print(f"[Watcher] FFI cross-language edges updated ({edges_created} edges).")
                    except Exception as e:
                        print(f"[Watcher] FFI re-linking skipped: {e}")
                except Exception as ex:
                    print(f"[arch watch] Error during automatic update: {ex}", file=sys.stderr)
                finally:
                    db_conn.close()
    except KeyboardInterrupt:
        print("\n[arch watch] Stopped.")
    finally:
        observer.stop()
        observer.join()
