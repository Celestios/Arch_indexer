import sys
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

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
    def detect_languages(project_dir: Path) -> List[str]:
        """Detects if the project contains Dart/Flutter, Rust, Go, TypeScript/JavaScript, Java, or Python source files."""
        languages = []
        # Check for Dart
        if (project_dir / "pubspec.yaml").exists() or any(project_dir.glob("**/pubspec.yaml")):
            languages.append("dart")
        # Check for Rust
        if (project_dir / "Cargo.toml").exists() or any(project_dir.glob("**/Cargo.toml")):
            languages.append("rust")
        # Check for Go
        if (project_dir / "go.mod").exists() or any(project_dir.glob("**/go.mod")):
            languages.append("go")
        # Check for TypeScript / JavaScript
        if (project_dir / "package.json").exists() or any(project_dir.glob("**/package.json")):
            languages.append("typescript")
        # Check for Java
        if (project_dir / "pom.xml").exists() or (project_dir / "build.gradle").exists() or any(project_dir.glob("**/pom.xml")) or any(project_dir.glob("**/build.gradle")):
            languages.append("java")
        # Check for Python
        if (project_dir / "requirements.txt").exists() or any(project_dir.glob("**/requirements.txt")) or any(project_dir.glob("**/*.py")):
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
        if language == "dart":
            print(f"[SCIP] Indexing Dart project under {project_dir}...")
            
            # 1. Check if dart is available
            if not shutil.which("dart"):
                print("Error: Dart SDK is not on the system PATH.", file=sys.stderr)
                return None
                
            # 2. Activate scip_dart globally if not already present
            # We run the activation command to ensure it's available
            try:
                subprocess.run(
                    ["dart", "pub", "global", "activate", "scip_dart"],
                    cwd=str(project_dir),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError as e:
                print(f"Warning: Failed to activate scip_dart: {e}", file=sys.stderr)

            # 3. Generate index
            try:
                # Runs the indexer. It generates index.scip at project_dir root
                subprocess.run(
                    ["dart", "pub", "global", "run", "scip_dart", "."],
                    cwd=str(project_dir),
                    check=True
                )
                index_path = project_dir / "index.scip"
                if index_path.exists():
                    return index_path
            except subprocess.CalledProcessError as e:
                print(f"Error executing scip_dart indexer: {e}", file=sys.stderr)
                return None

        elif language == "rust":
            print(f"[SCIP] Indexing Rust project under {project_dir}...")
            
            # 1. Determine the best way to call rust-analyzer
            ra_cmd = ["rust-analyzer", "scip", "."]
            if shutil.which("rustup"):
                # Fallback to calling it through rustup if toolchain shims are failing
                ra_cmd = ["rustup", "run", "stable", "rust-analyzer", "scip", "."]
                
            # 2. Run rust-analyzer indexer
            try:
                subprocess.run(ra_cmd, cwd=str(project_dir), check=True)
                index_path = project_dir / "index.scip"
                if index_path.exists():
                    return index_path
            except subprocess.CalledProcessError:
                # If stable toolchain lacks rust-analyzer, try adding the component
                print("Warning: rust-analyzer CLI was not found. Attempting to add it via rustup...")
                try:
                    subprocess.run(["rustup", "component", "add", "rust-analyzer"], check=True)
                    # Try again with direct command
                    subprocess.run(["rust-analyzer", "scip", "."], cwd=str(project_dir), check=True)
                    index_path = project_dir / "index.scip"
                    if index_path.exists():
                        return index_path
                except Exception as err:
                    print(f"Error: Failed to execute rust-analyzer scip: {err}", file=sys.stderr)
                    print("Notice: If you are using the rust-analyzer extension inside VS Code, the CLI component must still be installed globally.", file=sys.stderr)
                    print("To enable Rust indexing on the command-line, run:\n    rustup component add rust-analyzer", file=sys.stderr)
                    return None

        elif language == "go":
            print(f"[SCIP] Indexing Go project under {project_dir}...")
            if not shutil.which("scip-go"):
                print("Error: scip-go CLI is not on the system PATH.", file=sys.stderr)
                return None
            try:
                subprocess.run(["scip-go"], cwd=str(project_dir), check=True)
                index_path = project_dir / "index.scip"
                if index_path.exists():
                    return index_path
            except subprocess.CalledProcessError as e:
                print(f"Error executing scip-go: {e}", file=sys.stderr)
                return None

        elif language == "typescript":
            print(f"[SCIP] Indexing TypeScript/JavaScript project under {project_dir}...")
            if not shutil.which("scip-typescript"):
                print("Error: scip-typescript CLI is not on the system PATH.", file=sys.stderr)
                return None
            try:
                subprocess.run(["scip-typescript", "index"], cwd=str(project_dir), check=True)
                index_path = project_dir / "index.scip"
                if index_path.exists():
                    return index_path
            except subprocess.CalledProcessError as e:
                print(f"Error executing scip-typescript: {e}", file=sys.stderr)
                return None

        elif language == "java":
            print(f"[SCIP] Indexing Java project under {project_dir}...")
            if not shutil.which("scip-java"):
                print("Error: scip-java CLI is not on the system PATH.", file=sys.stderr)
                return None
            try:
                subprocess.run(["scip-java", "index"], cwd=str(project_dir), check=True)
                index_path = project_dir / "index.scip"
                if index_path.exists():
                    return index_path
            except subprocess.CalledProcessError as e:
                print(f"Error executing scip-java: {e}", file=sys.stderr)
                return None

        elif language == "python":
            print(f"[SCIP] Indexing Python project under {project_dir}...")
            if not shutil.which("scip-python"):
                print("Error: scip-python CLI is not on the system PATH.", file=sys.stderr)
                return None
            try:
                subprocess.run(["scip-python"], cwd=str(project_dir), check=True)
                index_path = project_dir / "index.scip"
                if index_path.exists():
                    return index_path
            except subprocess.CalledProcessError as e:
                print(f"Error executing scip-python: {e}", file=sys.stderr)
                return None
                    
        return None

    @staticmethod
    def parse_index(scip_file: Path) -> Dict[str, Any]:
        """
        Parses a binary index.scip file and returns a normalized dictionary
        of symbols, occurrences, and edges.
        """
        if not scip_file.exists():
            raise FileNotFoundError(f"SCIP index file not found at {scip_file}")

        index = scip_pb2.Index()
        with open(scip_file, "rb") as f:
            index.ParseFromString(f.read())

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
    def ingest_index(repository: Any, parsed_data: Dict[str, Any], embedder: Optional[Any] = None, project_root: Optional[Path] = None, force: bool = False):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Optionally uses an embedder to compute vector representations for symbol docstrings.
        """
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

        # Safety Check / Shrink Guard:
        # Check node/symbol count of new index versus the database
        new_symbols_count = len(parsed_data["symbols"])
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

        # Clean old symbols, occurrences, and edges for these files to prevent stale entries
        repository.files.clean_files_symbols_and_relations(file_list)

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

        # 2. Ingest symbols
        print(f"[SCIP Ingest] Ingesting {len(parsed_data['symbols'])} symbols into database...")
        symbols_to_ingest = []
        for sym_id, sym in parsed_data["symbols"].items():
            embedding = None
            if embedder and sym["docstring"]:
                try:
                    embedding = embedder.embed(sym["docstring"])
                except Exception as e:
                    print(f"Warning: Failed to generate embedding for {sym_id}: {e}", file=sys.stderr)
            
            symbols_to_ingest.append({
                "symbol": sym["symbol"],
                "filepath": sym["filepath"],
                "kind": sym["kind"],
                "signature": sym["signature"],
                "docstring": sym["docstring"],
                "body_hash": sym["body_hash"],
                "embedding": embedding
            })
        repository.symbols.upsert_symbols_bulk(symbols_to_ingest)

        # 3. Ingest occurrences
        print(f"[SCIP Ingest] Ingesting {len(parsed_data['occurrences'])} occurrences...")
        repository.symbols.add_occurrences_bulk(parsed_data["occurrences"])

        # 4. Ingest call graph edges (with calculated weights)
        print(f"[SCIP Ingest] Ingesting {len(parsed_data['edges'])} edges...")
        
        # Load config to calculate weights
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
        for edge in parsed_data["edges"]:
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
            
        repository.edges.add_edges_bulk(edges_to_ingest)

        # 5. Recalculate connection weights for symbols
        print("[SCIP Ingest] Recalculating symbol connection weights...")
        repository.symbols.recalculate_connection_weights()
        
        print("[SCIP Ingest] Ingestion complete.")



