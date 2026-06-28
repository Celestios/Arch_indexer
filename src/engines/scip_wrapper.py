import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add the parent directory of this file to the sys path so we can import scip_pb2
sys.path.insert(0, str(Path(__file__).parent))
try:
    import scip_pb2
except ImportError:
    # Fallback to absolute import path if needed
    from src.engines import scip_pb2

class ScipWrapper:
    """
    Wrapper for SCIP/LSIF code graph generators and parsers.
    Handles Dart/Flutter and Rust toolchain indexing and extracts normalized symbols & edges.
    """

    @staticmethod
    def detect_languages(project_dir: Path) -> List[str]:
        """Detects if the project contains Dart/Flutter or Rust source files."""
        languages = []
        # Check for Dart
        if (project_dir / "pubspec.yaml").exists() or any(project_dir.glob("**/pubspec.yaml")):
            languages.append("dart")
        # Check for Rust
        if (project_dir / "Cargo.toml").exists() or any(project_dir.glob("**/Cargo.toml")):
            languages.append("rust")
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
            "edges": []
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
    def ingest_index(repository: Any, parsed_data: Dict[str, Any], embedder: Optional[Any] = None):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Optionally uses an embedder to compute vector representations for symbol docstrings.
        """
        # 1. Register files first
        files_to_register = set()
        for occ in parsed_data["occurrences"]:
            if occ["filepath"]:
                files_to_register.add(occ["filepath"])
        for sym in parsed_data["symbols"].values():
            if sym["filepath"]:
                files_to_register.add(sym["filepath"])

        # Register files in bulk
        files_to_ingest = [
            {"filepath": fp, "sha256": "initial_hash", "language": "rust"}
            for fp in files_to_register
        ]
        repository.upsert_files_bulk(files_to_ingest)

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
        repository.upsert_symbols_bulk(symbols_to_ingest)

        # 3. Ingest occurrences
        print(f"[SCIP Ingest] Ingesting {len(parsed_data['occurrences'])} occurrences...")
        repository.add_occurrences_bulk(parsed_data["occurrences"])

        # 4. Ingest call graph edges
        print(f"[SCIP Ingest] Ingesting {len(parsed_data['edges'])} edges...")
        repository.add_edges_bulk(parsed_data["edges"])
        
        print("[SCIP Ingest] Ingestion complete.")


