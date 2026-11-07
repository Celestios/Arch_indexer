import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List

from utils.exclusions import load_include_dirs, load_exclude_patterns, is_included, is_excluded
from utils.helpers import infer_scip_kind, score_definition_candidate

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2


def extract_source_signature(lines: List[str], start_line: int, end_line: int) -> Optional[str]:
    """Extract a clean declaration signature from source lines (1-indexed)."""
    if not lines or start_line < 1 or start_line > len(lines):
        return None
    decl_lines = []
    max_l = min(start_line + 4, end_line if end_line >= start_line else start_line, len(lines))
    for i in range(start_line - 1, max_l):
        l = lines[i].strip()
        if not l:
            continue
        decl_lines.append(l)
        if l.endswith("{") or l.endswith(";") or (l.endswith(":") and not l.startswith("@")):
            break
    if not decl_lines:
        return None
    sig = " ".join(decl_lines)
    if sig.endswith("{"):
        sig = sig[:-1].strip()
    return sig[:300] if sig else None


def extract_source_docstring(lines: List[str], start_line: int) -> str:
    """Extract immediately preceding doc comments (///, /**, *, #, //) scanning upward (1-indexed)."""
    if not lines or start_line <= 1 or start_line > len(lines):
        return ""
    doc_lines = []
    idx = start_line - 2  # line right before start_line (0-indexed)
    comment_prefixes = ("///", "//", "#", "*", "/**", "/*!", "/*")

    if idx >= 0 and not lines[idx].strip():
        idx -= 1

    while idx >= 0:
        raw_l = lines[idx]
        stripped = raw_l.strip()
        if not stripped:
            break
        matched_prefix = None
        for p in comment_prefixes:
            if stripped.startswith(p):
                matched_prefix = p
                break
        if not matched_prefix:
            break

        content = stripped
        if content.startswith("///"):
            content = content[3:]
        elif content.startswith("//"):
            content = content[2:]
        elif content.startswith("/**"):
            content = content[3:].rstrip("*/")
        elif content.startswith("/*"):
            content = content[2:].rstrip("*/")
        elif content.startswith("*"):
            content = content[1:].rstrip("*/")
        elif content.startswith("#"):
            content = content[1:]
        doc_lines.append(content.strip())
        idx -= 1

    if not doc_lines:
        return ""
    doc_lines.reverse()
    return "\n".join(doc_lines)


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
        Filters by include_dirs and exclude from config.json if project_root is provided.
        """
        if not scip_file.exists():
            raise FileNotFoundError(f"SCIP index file not found at {scip_file}")

        include_dirs = load_include_dirs(project_root) if project_root else None
        exclude_patterns = load_exclude_patterns(project_root) if project_root else None

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

        # Cache file lines on disk to avoid repeated I/O during source grounding
        file_lines_cache: Dict[str, Optional[List[str]]] = {}

        def get_file_lines(rel_fp: str) -> Optional[List[str]]:
            if rel_fp in file_lines_cache:
                return file_lines_cache[rel_fp]
            if not project_root:
                return None
            target_path = project_root / rel_fp
            if not target_path.exists() or not target_path.is_file():
                file_lines_cache[rel_fp] = None
                return None
            try:
                with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    file_lines_cache[rel_fp] = lines
                    return lines
            except Exception:
                file_lines_cache[rel_fp] = None
                return None

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
                "body_hash": None,
                "start_line": 1,
                "end_line": 1,
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

            if is_excluded(resolved_filepath, exclude_patterns):
                continue
            if include_dirs and not is_included(resolved_filepath, include_dirs, exclude_patterns):
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

                    docs = meta["docs"]
                    sig = None
                    body_hash = None

                    # Source grounding: synthesize signature, docstring, and body hash from disk
                    flines = get_file_lines(resolved_filepath)
                    if flines:
                        sig = extract_source_signature(flines, start_line + 1, end_line + 1)
                        if not docs:
                            docs = extract_source_docstring(flines, start_line + 1)
                        if end_line >= start_line and start_line < len(flines):
                            span_text = "".join(flines[start_line:end_line + 1])
                            if span_text:
                                body_hash = hashlib.sha256(span_text.encode("utf-8")).hexdigest()[:16]

                    new_candidate = {
                        "symbol": symbol,
                        "filepath": resolved_filepath,
                        "kind": kind,
                        "signature": sig,
                        "docstring": docs,
                        "body_hash": body_hash,
                        "start_line": start_line + 1,
                        "end_line": end_line + 1,
                    }

                    # Deterministic canonical symbol disambiguation
                    if symbol in parsed_data["symbols"]:
                        existing = parsed_data["symbols"][symbol]
                        existing_score = score_definition_candidate(
                            existing,
                            filepath=existing.get("filepath"),
                            start_line=existing.get("start_line", 1),
                            end_line=existing.get("end_line", 1)
                        )
                        new_score = score_definition_candidate(
                            new_candidate,
                            filepath=resolved_filepath,
                            start_line=start_line + 1,
                            end_line=end_line + 1
                        )
                        if new_score > existing_score:
                            parsed_data["symbols"][symbol] = new_candidate
                    else:
                        parsed_data["symbols"][symbol] = new_candidate

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

            if is_excluded(resolved_filepath, exclude_patterns):
                continue
            if include_dirs and not is_included(resolved_filepath, include_dirs, exclude_patterns):
                continue

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

        # 4. Third pass: Missing symbol recovery / synthesis
        # Ensure any symbol referenced in occurrences exists in parsed_data["symbols"]
        for occ in parsed_data["occurrences"]:
            sym = occ["symbol"]
            if sym not in parsed_data["symbols"] and not sym.startswith("local "):
                parsed_data["symbols"][sym] = {
                    "symbol": sym,
                    "filepath": None,
                    "kind": infer_scip_kind(sym),
                    "signature": None,
                    "docstring": "",
                    "body_hash": None,
                    "start_line": 1,
                    "end_line": 1,
                }

        return parsed_data

