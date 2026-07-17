import sys
import os
import shutil
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

from utils.exclusions import load_include_dirs, is_included
from utils.helpers import IS_WINDOWS, ext_to_lang as _ext_to_lang


def print_progress(current: int, total: int, prefix: str = "", width: int = 30):
    """Print a progress bar that updates in-place."""
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = "=" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {current}/{total} ({pct*100:.0f}%)")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def run_with_scroll(cmd: list, cwd: str, max_lines: int = 10, shell: bool = False) -> int:
    """
    Runs a subprocess and displays only the last `max_lines` of output.
    Handles both \\n and \\r line endings (for tools like rust-analyzer that use \\r for progress).
    Older lines are removed from the top as new ones appear.
    Returns the process return code.
    """
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        shell=shell,
        bufsize=1
    )

    buffer = deque(maxlen=max_lines)
    lines_printed = 0
    partial_line = ""

    def _redraw():
        nonlocal lines_printed
        # Move cursor up to overwrite previously printed lines
        if lines_printed > 0:
            sys.stdout.write(f'\033[{lines_printed}A')
        # Clear and reprint each buffered line
        for bline in buffer:
            sys.stdout.write(f'\033[2K{bline}\n')
        # If the buffer shrank, clear any leftover stale lines
        leftover = lines_printed - len(buffer)
        for _ in range(leftover):
            sys.stdout.write('\033[2K\n')
        if leftover > 0:
            # Move cursor back up past the cleared leftover lines
            sys.stdout.write(f'\033[{leftover}A')
        lines_printed = len(buffer)
        sys.stdout.flush()

    try:
        while True:
            char = process.stdout.read(1)
            if not char:
                break

            if char in ('\r', '\n'):
                if partial_line.strip():
                    buffer.append(partial_line.strip())
                    _redraw()
                partial_line = ""
            else:
                partial_line += char
    except (KeyboardInterrupt, SystemExit):
        process.kill()
        raise
    finally:
        # Flush any remaining partial line
        if partial_line.strip():
            buffer.append(partial_line.strip())
            _redraw()
        process.stdout.close()

    return process.wait()

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2

# Add src to path to import change_tracker
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
from change_tracker.tracker import ChangeTracker

class ScipWrapper:
    """
    Wrapper for SCIP/LSIF code graph generators and parsers.
    Handles Dart/Flutter and Rust toolchain indexing and extracts normalized symbols & edges.
    """

    @staticmethod
    def _move_index_to_arch(project_dir: Path, language: str) -> Optional[Path]:
        """Move generated index.scip to .arch/index_{language}.scip."""
        index_path = project_dir / "index.scip"
        arch_index = project_dir / ".arch" / f"index_{language}.scip"
        if index_path.exists():
            arch_index.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(index_path), str(arch_index))
            return arch_index
        elif arch_index.exists():
            return arch_index
        return None

    @staticmethod
    def detect_languages(project_dir: Path) -> List[str]:
        """Detects if the project contains Dart/Flutter, Rust, Go, TypeScript/JavaScript, Java, or Python source files."""
        languages = []

        # Only check root-level project markers, not recursive subdirectories
        if (project_dir / "pubspec.yaml").exists():
            languages.append("dart")
        elif any(p.parent != project_dir for p in project_dir.rglob("pubspec.yaml")
                 if ".dart_tool" not in str(p) and "dart_analyzer" not in str(p)):
            languages.append("dart")
        if (project_dir / "Cargo.toml").exists():
            languages.append("rust")
        if (project_dir / "go.mod").exists():
            languages.append("go")
        if (project_dir / "package.json").exists():
            languages.append("typescript")
        if (project_dir / "pom.xml").exists() or (project_dir / "build.gradle").exists():
            languages.append("java")

        # Python: check for .py files in src/ only
        include_dirs = load_include_dirs(project_dir)
        def _filtered_glob(pattern):
            for p in project_dir.glob(pattern):
                if include_dirs is None or is_included(str(p.relative_to(project_dir)), include_dirs):
                    yield p

        if any(_filtered_glob("**/requirements.txt")) or any(_filtered_glob("**/*.py")):
            languages.append("python")
        return languages

    @staticmethod
    def verify_environment(languages: List[str]) -> Dict[str, bool]:
        """Checks if the required toolchains are installed and available."""
        status = {}
        if "dart" in languages:
            status["dart"] = shutil.which("dart") is not None
            
        if "rust" in languages:
            # Check if rust-analyzer or rustup is available
            has_rustup = shutil.which("rustup") is not None
            has_ra = shutil.which("rust-analyzer") is not None
            status["rust"] = has_rustup or has_ra

        if "go" in languages:
            status["go"] = shutil.which("scip-go") is not None

        if "typescript" in languages:
            status["typescript"] = shutil.which("scip-typescript") is not None

        if "java" in languages:
            status["java"] = shutil.which("scip-java") is not None

        if "python" in languages:
            status["python"] = shutil.which("scip-python") is not None
            
        return status

    @staticmethod
    def run_indexer(project_dir: Path, language: str) -> Optional[Path]:
        """
        Executes the language-specific SCIP indexer and returns the path to the generated index.scip.
        """
        handlers = {
            "dart": ScipWrapper._index_dart,
            "rust": ScipWrapper._index_rust,
            "go": ScipWrapper._index_generic,
            "typescript": ScipWrapper._index_generic,
            "java": ScipWrapper._index_generic,
            "python": ScipWrapper._index_python,
        }
        handler = handlers.get(language)
        if handler:
            return handler(project_dir, language)
        return None

    @staticmethod
    def _index_dart(project_dir: Path, language: str) -> Optional[Path]:
        print(f"[SCIP] Indexing Dart project under {project_dir}...")
        if not shutil.which("dart"):
            print("Error: Dart SDK is not on the system PATH.", file=sys.stderr)
            return None

        pubspec_dir = project_dir
        if not (project_dir / "pubspec.yaml").exists():
            pubspecs = [p for p in project_dir.rglob("pubspec.yaml")
                        if ".dart_tool" not in str(p) and "dart_analyzer" not in str(p)]
            if not pubspecs:
                print("[SCIP] No pubspec.yaml found, skipping Dart indexing.")
                return None
            pubspec_dir = pubspecs[0].parent
            print(f"[SCIP] Using pubspec at {pubspec_dir}")

        try:
            subprocess.run(
                ["dart", "pub", "global", "activate", "scip_dart"],
                cwd=str(pubspec_dir), check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=IS_WINDOWS
            )
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to activate scip_dart: {e}", file=sys.stderr)

        try:
            rc = run_with_scroll(
                ["dart", "pub", "global", "run", "scip_dart", "."],
                cwd=str(pubspec_dir), shell=IS_WINDOWS
            )
            if rc != 0:
                raise subprocess.CalledProcessError(rc, "scip_dart")
            return ScipWrapper._move_index_to_arch(project_dir, language)
        except subprocess.CalledProcessError as e:
            print(f"Error executing scip_dart indexer: {e}", file=sys.stderr)
            return None

    @staticmethod
    def _index_rust(project_dir: Path, language: str) -> Optional[Path]:
        print(f"[SCIP] Indexing Rust project under {project_dir}...")
        ra_cmd = ["rust-analyzer", "scip", "."]
        if shutil.which("rustup"):
            ra_cmd = ["rustup", "run", "stable", "rust-analyzer", "scip", "."]

        try:
            rc = run_with_scroll(ra_cmd, cwd=str(project_dir), shell=IS_WINDOWS)
            if rc != 0:
                raise subprocess.CalledProcessError(rc, "rust-analyzer")
            return ScipWrapper._move_index_to_arch(project_dir, language)
        except subprocess.CalledProcessError:
            print("Warning: rust-analyzer CLI was not found. Attempting to add it via rustup...")
            try:
                subprocess.run(["rustup", "component", "add", "rust-analyzer"], check=True, shell=IS_WINDOWS)
                rc = run_with_scroll(["rust-analyzer", "scip", "."], cwd=str(project_dir), shell=IS_WINDOWS)
                if rc != 0:
                    raise subprocess.CalledProcessError(rc, "rust-analyzer")
                return ScipWrapper._move_index_to_arch(project_dir, language)
            except Exception as err:
                print(f"Error: Failed to execute rust-analyzer scip: {err}", file=sys.stderr)
                print("Notice: If you are using the rust-analyzer extension inside VS Code, the CLI component must still be installed globally.", file=sys.stderr)
                print("To enable Rust indexing on the command-line, run:\n    rustup component add rust-analyzer", file=sys.stderr)
                return None

    @staticmethod
    def _index_generic(project_dir: Path, language: str) -> Optional[Path]:
        """Indexer for languages with simple `tool [subcommand]` invocations."""
        tool_map = {
            "go": ("scip-go", []),
            "typescript": ("scip-typescript", ["index"]),
            "java": ("scip-java", ["index"]),
        }
        tool_name, extra_args = tool_map.get(language, (f"scip-{language}", []))
        print(f"[SCIP] Indexing {language.capitalize()} project under {project_dir}...")
        if not shutil.which(tool_name):
            print(f"Error: {tool_name} CLI is not on the system PATH.", file=sys.stderr)
            return None
        try:
            rc = run_with_scroll([tool_name] + extra_args, cwd=str(project_dir), shell=IS_WINDOWS)
            if rc != 0:
                raise subprocess.CalledProcessError(rc, tool_name)
            return ScipWrapper._move_index_to_arch(project_dir, language)
        except subprocess.CalledProcessError as e:
            print(f"Error executing {tool_name}: {e}", file=sys.stderr)
            return None

    @staticmethod
    def _index_python(project_dir: Path, language: str) -> Optional[Path]:
        print(f"[SCIP] Indexing Python project under {project_dir}...")
        if not shutil.which("scip-python"):
            print("Error: scip-python CLI is not on the system PATH.", file=sys.stderr)
            return None
        try:
            arch_index = project_dir / ".arch" / f"index_{language}.scip"
            arch_index.parent.mkdir(parents=True, exist_ok=True)
            rc = run_with_scroll(
                ["scip-python", "index", "--project-name", str(project_dir.name),
                 "--output", str(arch_index)],
                cwd=str(project_dir), shell=IS_WINDOWS
            )
            if rc != 0:
                raise subprocess.CalledProcessError(rc, "scip-python")
            if arch_index.exists():
                return arch_index
        except subprocess.CalledProcessError as e:
            print(f"Error executing scip-python: {e}", file=sys.stderr)
            return None

    @staticmethod
    def parse_index(scip_file: Path, project_root: Optional[Path] = None) -> Dict[str, Any]:
        """
        Parses a binary index.scip file into a normalized dictionary
        of symbols, occurrences, and edges.
        Filters by include_dirs from config.json if project_root is provided.
        """
        if not scip_file.exists():
            raise FileNotFoundError(f"SCIP index file not found at {scip_file}")

        include_dirs = load_include_dirs(project_root) if project_root else None

        index = scip_pb2.Index()
        with open(scip_file, "rb") as f:
            raw = f.read()

        try:
            index.ParseFromString(raw)
        except Exception:
            raw = raw.replace(b'\xed\xa0\x80', b'___')
            raw = raw.replace(b'\xed\xa8\x80', b'___')
            raw = raw.replace(b'\xed\xb0\x80', b'___')
            raw = raw.replace(b'\xed\xbf\xbf', b'___')
            index.ParseFromString(raw)

        parsed_data = {
            "metadata": {
                "project_root": index.metadata.project_root,
                "tool_name": index.metadata.tool_info.name,
                "tool_version": index.metadata.tool_info.version
            },
            "symbols": {},
            "occurrences": [],
            "edges": [],
            "files": []
        }

        # 1. Parse external symbols (from external packages)
        for sym_info in index.external_symbols:
            docs = "\n".join(sym_info.documentation) if sym_info.documentation else ""
            kind_val = sym_info.kind
            kind_str = scip_pb2.SymbolInformation.Kind.Name(kind_val) if kind_val in scip_pb2.SymbolInformation.Kind.values() else "UnspecifiedKind"
            
            parsed_data["symbols"][sym_info.symbol] = {
                "symbol": sym_info.symbol,
                "filepath": None,
                "kind": kind_str,
                "signature": None,
                "docstring": docs,
                "body_hash": None
            }

        # 2. First pass: Extract local symbol definitions & hover/docstrings
        for document in index.documents:
            filepath = document.relative_path
            if include_dirs and not is_included(filepath, include_dirs):
                continue
            parsed_data["files"].append(filepath)
            
            # Map symbol metadata inside this file
            symbol_metadata = {}
            for sym_info in document.symbols:
                docs = "\n".join(sym_info.documentation) if sym_info.documentation else ""
                kind_val = sym_info.kind
                kind_str = scip_pb2.SymbolInformation.Kind.Name(kind_val) if kind_val in scip_pb2.SymbolInformation.Kind.values() else "UnspecifiedKind"
                
                symbol_metadata[sym_info.symbol] = {
                    "docs": docs,
                    "kind": kind_str
                }

            # Parse occurrences inside this file
            for occ in document.occurrences:
                symbol = occ.symbol
                
                # Check if this occurrence is a definition (SymbolRole = 1)
                is_definition = bool(occ.symbol_roles & 1)
                
                r = occ.range
                if len(r) == 3:
                    start_line, start_col, end_line, end_col = r[0], r[1], r[0], r[2]
                elif len(r) == 4:
                    start_line, start_col, end_line, end_col = r[0], r[1], r[2], r[3]
                else:
                    continue  # Invalid range format

                # Record occurrence coordinates
                parsed_data["occurrences"].append({
                    "symbol": symbol,
                    "filepath": filepath,
                    "start_line": start_line + 1,  # SCIP uses 0-based lines
                    "start_col": start_col,
                    "end_line": end_line + 1,
                    "end_col": end_col,
                    "role": occ.symbol_roles
                })

                # Register as a local definition symbol if role includes definition
                if is_definition and not symbol.startswith("local "):
                    meta = symbol_metadata.get(symbol, {"docs": "", "kind": "UnspecifiedKind"})
                    
                    parsed_data["symbols"][symbol] = {
                        "symbol": symbol,
                        "filepath": filepath,
                        "kind": meta["kind"],
                        "signature": None,
                        "docstring": meta["docs"],
                        "body_hash": None
                    }

        # 3. Second pass: Extract call & reference edges
        # Pre-group definition occurrences by filepath to avoid O(N * M) nested loops
        occurrences_by_file = {}
        for occ in parsed_data["occurrences"]:
            # Check if role contains Definition (bit 0)
            if (occ["role"] & 1) and occ["symbol"] in parsed_data["symbols"]:
                fp = occ["filepath"]
                if fp not in occurrences_by_file:
                    occurrences_by_file[fp] = []
                occurrences_by_file[fp].append(occ)

        # Sort the occurrences of each file by span size (smallest first) so innermost definitions win
        for fp, defs in occurrences_by_file.items():
            defs.sort(key=lambda d: d["end_line"] - d["start_line"])

        for document in index.documents:
            filepath = document.relative_path
            
            # Fetch pre-grouped definition occurrences for this file
            file_defs = occurrences_by_file.get(filepath, [])

            for occ in document.occurrences:
                symbol = occ.symbol
                is_reference = not bool(occ.symbol_roles & 1)
                
                # Check if target is a known symbol (local or external)
                if not is_reference or symbol.startswith("local ") or symbol not in parsed_data["symbols"]:
                    continue
                
                ref_line = occ.range[0] + 1
                
                # Find which definition encompasses this reference call range
                caller_symbol = None
                for def_occ in file_defs:
                    if def_occ["start_line"] <= ref_line <= def_occ["end_line"]:
                        caller_symbol = def_occ["symbol"]
                        break
                
                if caller_symbol and caller_symbol != symbol:
                    parsed_data["edges"].append({
                        "source": caller_symbol,
                        "target": symbol,
                        "relation": "Calls"
                    })

        return parsed_data

    @staticmethod
    def _get_symbol_layer(filepath: str, config: Dict[str, Any]) -> str:
        if not filepath:
            return ""
        norm_path = filepath.replace("\\", "/")
        best_prefix = ""
        best_conf = None
        for prefix, prefix_conf in config.items():
            if norm_path.startswith(prefix) and len(prefix) > len(best_prefix):
                best_prefix = prefix
                best_conf = prefix_conf
        if not best_conf:
            return ""
        
        layer_conf = best_conf.get("automatic_fields", {}).get("layer", {})
        if not layer_conf:
            return ""
        
        assigned_val = layer_conf.get("default", "")
        rules = layer_conf.get("assignment_rules", [])
        for rule in rules:
            conds = rule.get("conditions", {})
            val = rule.get("value")
            if conds.get("path_prefix") and norm_path.startswith(conds["path_prefix"]):
                assigned_val = val
                break
        return assigned_val

    @staticmethod
    def calculate_edge_weight(source_filepath: str, target_filepath: str, config: Dict[str, Any]) -> float:
        if not source_filepath or not target_filepath:
            return 1.0
        
        src_layer = ScipWrapper._get_symbol_layer(source_filepath, config)
        tgt_layer = ScipWrapper._get_symbol_layer(target_filepath, config)
        
        weight = 1.0
        if src_layer and tgt_layer:
            if src_layer == tgt_layer:
                weight *= 1.5
            else:
                for prefix_conf in config.values():
                    rules = prefix_conf.get("automatic_fields", {}).get("layer", {}).get("rules", [])
                    for rule in rules:
                        if rule.get("source") == src_layer and rule.get("target") == tgt_layer:
                            weight *= 0.5
                            break
        return weight

    @staticmethod
    def ingest_index(repository: Any, parsed_data: Dict[str, Any], embedder: Optional[Any] = None, project_root: Optional[Path] = None, force: bool = False, config: Optional[Dict[str, Any]] = None):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Optionally uses an embedder to compute vector representations for symbol docstrings.
        Uses incremental ingestion: only processes files whose content has changed.
        """
        from change_tracker.tracker import ChangeTracker

        # 1. Register files first
        files_to_register = set(parsed_data.get("files", []))
        for occ in parsed_data["occurrences"]:
            if occ["filepath"]:
                files_to_register.add(occ["filepath"])
        for sym in parsed_data["symbols"].values():
            if sym["filepath"]:
                files_to_register.add(sym["filepath"])

        file_list = list(files_to_register)

        # Identify languages present in the new index and clean up deleted files
        languages_in_index = set()
        for fp in file_list:
            ext = Path(fp).suffix.lower()
            lang = "rust" if ext == ".rs" else ("dart" if ext == ".dart" else "unknown")
            languages_in_index.add(lang)

        db_files = repository.files.get_all_files_metadata()

        # Fallback: if the new index is empty, use languages detected in the project or database
        if not languages_in_index:
            if project_root:
                try:
                    languages_in_index = set(ScipWrapper.detect_languages(project_root))
                except Exception:
                    pass
            if not languages_in_index:
                for fp, meta in db_files.items():
                    if meta.get("language"):
                        languages_in_index.add(meta.get("language"))

        deleted_files = []
        for fp, meta in db_files.items():
            file_lang = meta.get("language")
            if file_lang in languages_in_index and fp not in files_to_register:
                # A file is considered deleted only if it does NOT exist on disk
                exists_on_disk = False
                if project_root:
                    try:
                        exists_on_disk = (project_root / fp).exists()
                    except Exception:
                        pass
                if not exists_on_disk:
                    deleted_files.append(fp)

        # 2. Determine which files actually changed (incremental)
        changed_files = []
        unchanged_files = []
        if project_root and not force:
            for fp in file_list:
                abs_path = project_root / fp
                current_hash = ChangeTracker.calculate_sha256(abs_path)
                db_hash = db_files.get(fp, {}).get("sha256", "")
                if current_hash != db_hash:
                    changed_files.append(fp)
                else:
                    unchanged_files.append(fp)

            # 2b. Transitive invalidation: expand changed set to include dependents
            if changed_files:
                from change_tracker.invalidation import TransitiveInvalidation
                invalidator = TransitiveInvalidation(repository, max_depth=2)
                changed_files = list(invalidator.expand_changed_files(changed_files))
                print(f"[SCIP Ingest] Incremental: {len(changed_files)} to process (including dependents), {len(unchanged_files)} unchanged")
        else:
            changed_files = file_list
            unchanged_files = []

        # Safety Check / Shrink Guard (skip for incremental)
        if force or not unchanged_files:
            new_symbols_count = sum(1 for v in parsed_data["symbols"].values() if v["filepath"])
            existing_symbols_count = 0
            langs_tuple = tuple(languages_in_index)
            if langs_tuple:
                with repository.db_conn.session() as conn:
                    if len(langs_tuple) == 1:
                        res = conn.execute(
                            "SELECT COUNT(*) FROM symbols WHERE filepath IN (SELECT filepath FROM files WHERE language = ?)",
                            (langs_tuple[0],)
                        ).fetchone()
                    else:
                        placeholders = ",".join("?" for _ in langs_tuple)
                        res = conn.execute(
                            f"SELECT COUNT(*) FROM symbols WHERE filepath IN (SELECT filepath FROM files WHERE language IN ({placeholders}))",
                            langs_tuple
                        ).fetchone()
                    if res:
                        existing_symbols_count = res[0]

            if not force and len(deleted_files) == 0 and existing_symbols_count > 0 and new_symbols_count < existing_symbols_count:
                raise ValueError(
                    f"Shrink Guard: New index has {new_symbols_count} symbols, but database has {existing_symbols_count} existing symbols for {languages_in_index}. "
                    "Refusing to overwrite. This might be due to a failed SCIP extraction. Pass force=True to override."
                )

        # Clean up deleted files
        for fp in deleted_files:
            print(f"[SCIP Ingest] Cleaning up deleted file from database: {fp}")
            repository.files.delete_file(fp)

        # Register files in bulk with actual SHA-256 hashes
        files_to_ingest = []
        for fp in file_list:
            sha256_val = "initial_hash"
            if project_root:
                abs_path = project_root / fp
                sha256_val = ChangeTracker.calculate_sha256(abs_path)
            
            # Detect language based on extension
            ext = Path(fp).suffix.lower()
            lang = "rust" if ext == ".rs" else ("dart" if ext == ".dart" else "unknown")
            files_to_ingest.append({"filepath": fp, "sha256": sha256_val, "language": lang})

        repository.files.upsert_files_bulk(files_to_ingest)

        # Early exit: if nothing changed and nothing was deleted, skip ingestion
        if not changed_files and not deleted_files:
            print("[SCIP Ingest] No files changed. Skipping symbol/occurrence/edge ingestion.")
            return

        # 2. Ingest symbols (only changed files + all external symbols)
        changed_set = set(changed_files)
        filtered_symbols = {k: v for k, v in parsed_data["symbols"].items()
                          if v["filepath"] is None or v["filepath"] in changed_set}
        total_symbols = len(filtered_symbols)
        print(f"[SCIP Ingest] Ingesting {total_symbols} symbols from {len(changed_files)} changed files...")

        # Load existing symbols from DB to compare
        existing_symbols = {}
        if changed_files:
            existing_symbols = repository.symbols.get_symbols_by_filepaths(changed_files)

        items = list(filtered_symbols.items())

        def process_symbol(item):
            sym_id, sym = item
            # Skip if symbol exists and hasn't changed
            if sym_id in existing_symbols:
                existing = existing_symbols[sym_id]
                if (existing["body_hash"] == sym["body_hash"] and
                    existing["kind"] == sym["kind"] and
                    existing["signature"] == sym.get("signature") and
                    existing["docstring"] == sym["docstring"]):
                    return None  # Skip unchanged
            embedding = None
            if embedder and sym["docstring"]:
                try:
                    embedding = embedder.embed(sym["docstring"])
                except Exception as e:
                    print(f"Warning: Failed to generate embedding for {sym_id}: {e}", file=sys.stderr)
            return {
                "symbol": sym["symbol"],
                "filepath": sym["filepath"],
                "kind": sym["kind"],
                "signature": sym["signature"],
                "docstring": sym["docstring"],
                "body_hash": sym["body_hash"],
                "embedding": embedding
            }

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(process_symbol, item): idx for idx, item in enumerate(items)}
            completed = 0
            results = [None] * len(items)
            for future in as_completed(futures):
                original_idx = futures[future]
                results[original_idx] = future.result()
                completed += 1
                if completed % 100 == 0 or completed == total_symbols:
                    print_progress(completed, total_symbols, prefix="[SCIP Ingest] Symbols")
            symbols_to_ingest = [r for r in results if r is not None]

        skipped = total_symbols - len(symbols_to_ingest)
        if skipped > 0:
            print(f"  Skipped {skipped} unchanged symbols.")
        print(f"[SCIP Ingest] Writing {len(symbols_to_ingest)} symbols to database...")
        sym_chunk = 100
        for i in range(0, len(symbols_to_ingest), sym_chunk):
            chunk = symbols_to_ingest[i:i + sym_chunk]
            repository.symbols.upsert_symbols_bulk(chunk)
            print_progress(min(i + sym_chunk, len(symbols_to_ingest)), len(symbols_to_ingest), prefix="[SCIP Ingest] Symbols DB")

        # 3. Ingest occurrences (only changed files)
        filtered_occurrences = [occ for occ in parsed_data["occurrences"]
                               if occ["filepath"] and occ["filepath"] in changed_set]
        total_occ = len(filtered_occurrences)
        # Delete old occurrences for changed files before re-inserting
        for fp in changed_files:
            repository.symbols.delete_occurrences_for_file(fp)
        print(f"[SCIP Ingest] Ingesting {total_occ} occurrences...")
        occ_chunk = 100
        for i in range(0, total_occ, occ_chunk):
            chunk = filtered_occurrences[i:i + occ_chunk]
            repository.symbols.add_occurrences_bulk(chunk)
            print_progress(min(i + occ_chunk, total_occ), total_occ, prefix="[SCIP Ingest] Occurrences")

        # 4. Ingest call graph edges (only changed files)
        filtered_edges = [e for e in parsed_data["edges"]
                         if filtered_symbols.get(e["source"], {}).get("filepath") in changed_set
                         or filtered_symbols.get(e["target"], {}).get("filepath") in changed_set]
        total_edges = len(filtered_edges)
        # Delete old edges for changed files before re-inserting
        for fp in changed_files:
            repository.edges.delete_edges_for_file(fp)
        print(f"[SCIP Ingest] Ingesting {total_edges} edges from changed files...")
        
        # Load config to calculate weights
        if config is None:
            config = {}
            if project_root:
                config_path = project_root / ".arch" / "config.json"
                if config_path.exists():
                    try:
                        import json
                        with open(config_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                    except Exception:
                        pass

        edges_to_ingest = []
        for idx, edge in enumerate(filtered_edges, 1):
            # Find filepath for caller and callee to calculate edge weight
            caller_sym = edge["source"]
            callee_sym = edge["target"]
            caller_fp = parsed_data["symbols"].get(caller_sym, {}).get("filepath")
            callee_fp = parsed_data["symbols"].get(callee_sym, {}).get("filepath")
            
            weight = ScipWrapper.calculate_edge_weight(caller_fp, callee_fp, config)
            edges_to_ingest.append({
                "source": caller_sym,
                "target": callee_sym,
                "relation": edge["relation"],
                "weight": weight
            })
            if idx % 100 == 0 or idx == total_edges:
                print_progress(idx, total_edges, prefix="[SCIP Ingest] Edges")
            
        repository.edges.add_edges_bulk(edges_to_ingest)

        # 5. Recalculate connection weights for symbols
        print("[SCIP Ingest] Recalculating symbol connection weights...")
        repository.symbols.recalculate_connection_weights()
        
        print("[SCIP Ingest] Ingestion complete.")



