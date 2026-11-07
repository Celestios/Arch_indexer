from pathlib import Path
from typing import Dict, Any, Optional

from utils.exclusions import load_include_dirs, is_included
from utils.helpers import infer_scip_kind

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2


def _detect_scip_run_dir(scip_file: Path, project_root: Path, metadata_uri: Optional[str]) -> Path:
    # 1. Try to parse from metadata URI
    if metadata_uri:
        from urllib.parse import unquote
        try:
            if metadata_uri.startswith("file://"):
                path_str = metadata_uri[7:]
            elif metadata_uri.startswith("file:/"):
                path_str = metadata_uri[6:]
            else:
                path_str = None

            if path_str:
                path_str = unquote(path_str).replace("\\", "/")
                if path_str.startswith("/") and len(path_str) > 2 and path_str[2] == ":":
                    path_str = path_str[1:]
                run_dir = Path(path_str)
                if run_dir != Path(".") and run_dir.exists():
                    return run_dir
        except Exception:
            pass

    # 2. Fallback based on scip_file name and project_root structure
    if "rust" in scip_file.name:
        if (project_root / "rust" / "Cargo.toml").exists():
            return project_root / "rust"
        for p in project_root.rglob("Cargo.toml"):
            if "target" not in str(p) and ".arch" not in str(p):
                return p.parent
    elif "dart" in scip_file.name:
        if (project_root / "pubspec.yaml").exists():
            return project_root
        for p in project_root.rglob("pubspec.yaml"):
            if ".dart_tool" not in str(p) and "dart_analyzer" not in str(p):
                return p.parent

    return project_root


class ScipParser:
    """Parses binary SCIP index files into normalized Python dictionaries."""

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

        scip_run_dir = None
        if project_root:
            scip_run_dir = _detect_scip_run_dir(scip_file, project_root, index.metadata.project_root)

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
            resolved_filepath = filepath
            if project_root and scip_run_dir:
                try:
                    abs_path = scip_run_dir / filepath
                    resolved_filepath = str(abs_path.relative_to(project_root)).replace("\\", "/")
                except ValueError:
                    pass

            if include_dirs and not is_included(resolved_filepath, include_dirs):
                continue
            parsed_data["files"].append(resolved_filepath)

            symbol_metadata = {}
            for sym_info in document.symbols:
                docs = "\n".join(sym_info.documentation) if sym_info.documentation else ""
                kind_val = sym_info.kind
                kind_str = scip_pb2.SymbolInformation.Kind.Name(kind_val) if kind_val in scip_pb2.SymbolInformation.Kind.values() else "UnspecifiedKind"

                symbol_metadata[sym_info.symbol] = {
                    "docs": docs,
                    "kind": kind_str
                }

            for occ in document.occurrences:
                symbol = occ.symbol
                is_definition = bool(occ.symbol_roles & 1)

                r = occ.range
                if is_definition:
                    enc = getattr(occ, "enclosing_range", None)
                    if enc is not None:
                        try:
                            if len(enc) in (3, 4):
                                r = enc
                        except (TypeError, AttributeError):
                            pass

                if len(r) == 3:
                    start_line, start_col, end_line, end_col = r[0], r[1], r[0], r[2]
                elif len(r) == 4:
                    start_line, start_col, end_line, end_col = r[0], r[1], r[2], r[3]
                else:
                    continue

                parsed_data["occurrences"].append({
                    "symbol": symbol,
                    "filepath": resolved_filepath,
                    "start_line": start_line + 1,
                    "start_col": start_col,
                    "end_line": end_line + 1,
                    "end_col": end_col,
                    "role": occ.symbol_roles
                })

                if is_definition and not symbol.startswith("local "):
                    meta = symbol_metadata.get(symbol, {"docs": "", "kind": "UnspecifiedKind"})
                    kind = meta["kind"]
                    if kind == "UnspecifiedKind" or not kind:
                        kind = infer_scip_kind(symbol)

                    parsed_data["symbols"][symbol] = {
                        "symbol": symbol,
                        "filepath": resolved_filepath,
                        "kind": kind,
                        "signature": None,
                        "docstring": meta["docs"],
                        "body_hash": None
                    }

        # 3. Second pass: Extract call & reference edges
        occurrences_by_file = {}
        for occ in parsed_data["occurrences"]:
            sym = occ["symbol"]
            if (occ["role"] & 1) and sym in parsed_data["symbols"]:
                # Exclude parameters and fields as enclosing callers
                if sym.endswith(")") or (sym.endswith(".") and not sym.endswith("().")):
                    continue
                fp = occ["filepath"]
                if fp not in occurrences_by_file:
                    occurrences_by_file[fp] = []
                occurrences_by_file[fp].append(occ)

        for fp, defs in occurrences_by_file.items():
            defs.sort(key=lambda d: d["end_line"] - d["start_line"])

        for document in index.documents:
            filepath = document.relative_path
            resolved_filepath = filepath
            if project_root and scip_run_dir:
                try:
                    abs_path = scip_run_dir / filepath
                    resolved_filepath = str(abs_path.relative_to(project_root)).replace("\\", "/")
                except ValueError:
                    pass

            file_defs = occurrences_by_file.get(resolved_filepath, [])

            for occ in document.occurrences:
                symbol = occ.symbol
                is_reference = not bool(occ.symbol_roles & 1)

                if (
                    not is_reference
                    or symbol.startswith("local ")
                    or symbol.endswith(")")
                    or symbol not in parsed_data["symbols"]
                ):
                    continue

                ref_line = occ.range[0] + 1

                caller_symbol = None
                for def_occ in file_defs:
                    if def_occ["start_line"] <= ref_line <= def_occ["end_line"]:
                        caller_symbol = def_occ["symbol"]
                        break

                if (
                    caller_symbol
                    and caller_symbol != symbol
                    and not caller_symbol.startswith("local ")
                    and not symbol.startswith("local ")
                ):
                    parsed_data["edges"].append({
                        "source": caller_symbol,
                        "target": symbol,
                        "relation": "Calls"
                    })

        return parsed_data

