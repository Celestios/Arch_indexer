from pathlib import Path
from typing import Dict, Any, Optional

from utils.exclusions import load_include_dirs, is_included

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2


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
                if len(r) == 3:
                    start_line, start_col, end_line, end_col = r[0], r[1], r[0], r[2]
                elif len(r) == 4:
                    start_line, start_col, end_line, end_col = r[0], r[1], r[2], r[3]
                else:
                    continue

                parsed_data["occurrences"].append({
                    "symbol": symbol,
                    "filepath": filepath,
                    "start_line": start_line + 1,
                    "start_col": start_col,
                    "end_line": end_line + 1,
                    "end_col": end_col,
                    "role": occ.symbol_roles
                })

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
        occurrences_by_file = {}
        for occ in parsed_data["occurrences"]:
            if (occ["role"] & 1) and occ["symbol"] in parsed_data["symbols"]:
                fp = occ["filepath"]
                if fp not in occurrences_by_file:
                    occurrences_by_file[fp] = []
                occurrences_by_file[fp].append(occ)

        for fp, defs in occurrences_by_file.items():
            defs.sort(key=lambda d: d["end_line"] - d["start_line"])

        for document in index.documents:
            filepath = document.relative_path
            file_defs = occurrences_by_file.get(filepath, [])

            for occ in document.occurrences:
                symbol = occ.symbol
                is_reference = not bool(occ.symbol_roles & 1)

                if not is_reference or symbol.startswith("local ") or symbol not in parsed_data["symbols"]:
                    continue

                ref_line = occ.range[0] + 1

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
