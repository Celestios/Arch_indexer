import os
import sys
import time
from pathlib import Path
from typing import Set

from db.connection import DbConnection
from db.repository import Repository
from engines.registry import LanguageRegistry
from engines.scip_wrapper import ScipWrapper
from engines.treesitter import TreesitterEngine
from change_tracker.tracker import ChangeTracker
from auditor.analyzer import Auditor
from engines.ffi_linker import FfiLinker
from utils.exclusions import load_include_dirs, is_included

_WATCHED_EXTENSIONS = set(LanguageRegistry._extension_map.keys())


def _resolve_package_root(file_path: Path, project_root: Path, lang: str) -> Path:
    """Find the nearest directory containing Cargo.toml or pubspec.yaml (or other package manifests)."""
    manifest_name = {
        "rust": "Cargo.toml",
        "dart": "pubspec.yaml",
        "go": "go.mod",
        "typescript": "package.json",
        "java": "pom.xml",
        "python": "requirements.txt",
    }.get(lang)
    if not manifest_name:
        return project_root

    curr = file_path.resolve()
    if curr.is_file():
        curr = curr.parent

    proj_resolved = project_root.resolve()
    while True:
        if (curr / manifest_name).exists():
            return curr
        if curr == proj_resolved or curr.parent == curr:
            break
        curr = curr.parent

    return project_root


_FFI_BRIDGE_INDICATORS = ("frb_generated", "bridge", "ffi", "_generated")


def _has_ffi_bridge_files(files) -> bool:
    """Check if any file in the batch belongs to an FFI bridge directory or filename pattern."""
    for f in files:
        f_str = str(f).replace("\\", "/").lower()
        if any(indicator in f_str for indicator in _FFI_BRIDGE_INDICATORS):
            return True
    return False


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

            # --- Tier 1: Immediate Tree-sitter AST Sync (< 2ms) ---
            if path.exists() and path.is_file():
                t0 = time.perf_counter()
                try:
                    rel_fp = str(path.resolve().relative_to(project_root)).replace("\\", "/")
                except ValueError:
                    rel_fp = str(path).replace("\\", "/")

                try:
                    db_conn_tier1 = DbConnection(db_path)
                    repo_tier1 = Repository(db_conn_tier1)
                    decls = TreesitterEngine.sync_file_to_db(repo_tier1, path)
                    db_conn_tier1.close()
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    if decls:
                        print(f"[arch watch] [AST Tier-1] Synced {len(decls)} symbols from {rel_fp} ({elapsed_ms:.1f}ms)")
                except Exception as ast_err:
                    print(f"[arch watch] [AST Tier-1] Warning syncing {rel_fp}: {ast_err}", file=sys.stderr)

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
                    # 1. Filter changed files by comparing filesystem hashes against repository.files.get_all_files_metadata()
                    db_files = repository.files.get_all_files_metadata()
                    dirty_files: Set[str] = set()
                    for p in batch:
                        try:
                            rel_fp = str(p.resolve().relative_to(project_root)).replace("\\", "/")
                        except ValueError:
                            rel_fp = str(p).replace("\\", "/")

                        if not p.exists():
                            dirty_files.add(rel_fp)
                            continue

                        curr_hash = ChangeTracker.calculate_sha256(p)
                        db_hash = db_files.get(rel_fp, {}).get("sha256", "")
                        if curr_hash != db_hash:
                            dirty_files.add(rel_fp)

                    if not dirty_files:
                        print("[arch watch] No file content changes detected after hashing. Skipping re-indexing.")
                        continue

                    # 2. Sub-crate / Sub-package scoping
                    package_targets = set()
                    for p in batch:
                        try:
                            rel_fp = str(p.resolve().relative_to(project_root)).replace("\\", "/")
                        except ValueError:
                            rel_fp = str(p).replace("\\", "/")
                        if rel_fp not in dirty_files:
                            continue
                        lang = LanguageRegistry.detect_language(str(p))
                        if not lang:
                            continue
                        pkg_root = _resolve_package_root(p, project_root, lang)
                        package_targets.add((lang, pkg_root))

                    if not package_targets:
                        languages = ScipWrapper.detect_languages(project_root)
                        package_targets = {(lang, project_root) for lang in languages}

                    indexed_any = False
                    for lang, pkg_root in package_targets:
                        print(f"[arch watch] Running indexer for {lang} under {pkg_root}...")
                        index_path = ScipWrapper.run_indexer(pkg_root, lang)
                        if index_path:
                            parsed = ScipWrapper.parse_index(index_path, project_root, changed_files=dirty_files)
                            ScipWrapper.ingest_index(repository, parsed, project_root=project_root)
                            indexed_any = True
                    
                    if indexed_any:
                        print("[arch watch] Re-indexing complete. Running compliance audit...")
                        auditor = Auditor(repository, project_root)
                        violations = []
                        if len(dirty_files) == 1:
                            violations = auditor.run_audit(filepath_filter=next(iter(dirty_files)))
                        else:
                            try:
                                common_prefix = os.path.commonpath(list(dirty_files)).replace("\\", "/")
                                if common_prefix and common_prefix != ".":
                                    violations = auditor.run_audit(filepath_filter=common_prefix)
                                else:
                                    for fp in dirty_files:
                                        violations.extend(auditor.run_audit(filepath_filter=fp))
                            except Exception:
                                for fp in dirty_files:
                                    violations.extend(auditor.run_audit(filepath_filter=fp))

                        if violations:
                            print(f"[arch watch] Found {len(violations)} violations:")
                            for v in violations:
                                print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} — {v['message']}")
                        else:
                            print("[arch watch] Audit complete. No violations found.")
                    else:
                        print("[arch watch] Re-indexing failed.")

                    # Re-run FFI bridge linking only if bridge files changed
                    if _has_ffi_bridge_files(batch):
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
