"""SCIP binary index parser with Pass-0 canonical workspace identity resolution."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

from utils.exclusions import is_excluded, is_included, load_exclude_patterns, load_include_dirs
from utils.helpers import infer_scip_kind, score_definition_candidate
from utils.symbol_id import parse_canonical_id, scip_to_canonical_id

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2

logger = logging.getLogger(__name__)


def _is_int(val: Any) -> bool:
    return type(val) is int


def normalize_range(occ: Any, use_enclosing: bool = False) -> Optional[Tuple[int, int, int, int]]:
    """
    Normalizes a SCIP protobuf Occurrence range into (start_line, start_col, end_line, end_col).
    Supports both legacy occ.range/occ.enclosing_range and modern typed_range oneof fields.
    """
    has_field = getattr(occ, "HasField", None)

    if use_enclosing:
        if has_field:
            try:
                if occ.HasField("single_line_enclosing_range") is True:
                    sl = occ.single_line_enclosing_range
                    return (sl.line, sl.start_character, sl.line, sl.end_character)
                if occ.HasField("multi_line_enclosing_range") is True:
                    ml = occ.multi_line_enclosing_range
                    return (ml.start_line, ml.start_character, ml.end_line, ml.end_character)
            except (TypeError, ValueError):
                pass

        enc = getattr(occ, "enclosing_range", None)
        if enc is not None:
            try:
                if len(enc) == 3 and all(_is_int(x) for x in enc):
                    return (enc[0], enc[1], enc[0], enc[2])
                if len(enc) == 4 and all(_is_int(x) for x in enc):
                    return (enc[0], enc[1], enc[2], enc[3])
            except (TypeError, IndexError):
                pass

    if has_field:
        try:
            if occ.HasField("single_line_range") is True:
                sl = occ.single_line_range
                return (sl.line, sl.start_character, sl.line, sl.end_character)
            if occ.HasField("multi_line_range") is True:
                ml = occ.multi_line_range
                return (ml.start_line, ml.start_character, ml.end_line, ml.end_character)
        except (TypeError, ValueError):
            pass

    r = getattr(occ, "range", None)
    if r is not None:
        try:
            if len(r) == 3 and all(_is_int(x) for x in r):
                return (r[0], r[1], r[0], r[2])
            if len(r) == 4 and all(_is_int(x) for x in r):
                return (r[0], r[1], r[2], r[3])
        except (TypeError, IndexError):
            pass

    return None


def _detect_scip_run_dir(scip_file: Path, project_root: Path, metadata_uri: Optional[str]) -> Path:
    if metadata_uri:
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


def _kind_name(kind_val: int) -> str:
    if kind_val in scip_pb2.SymbolInformation.Kind.values():
        return scip_pb2.SymbolInformation.Kind.Name(kind_val)
    return "UnspecifiedKind"


def parse_index(
    scip_file: Path,
    project_root: Optional[Path] = None,
    changed_files: Optional[Any] = None,
    ast_spans_by_file: Optional[Dict[str, List[Tuple[int, int, str]]]] = None,
    existing_scip_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Parses a binary index.scip file into canonical symbols, occurrences, diagnostics, and edges.
    Uses a Pass-0 workspace definition scan so cross-file references never poison the SCIP->canonical cache.
    """
    if not scip_file.exists():
        raise FileNotFoundError(f"SCIP index file not found at {scip_file}")

    changed_set: Optional[Set[str]] = None
    if changed_files is not None:
        changed_set = set()
        for f in changed_files:
            p = Path(f)
            if project_root and p.is_absolute():
                try:
                    rel = str(p.relative_to(project_root)).replace("\\", "/")
                except ValueError:
                    rel = str(p).replace("\\", "/")
            else:
                rel = str(p).replace("\\", "/")
            if rel.startswith("./"):
                rel = rel[2:]
            changed_set.add(rel)

    include_dirs = load_include_dirs(project_root) if project_root else None
    exclude_patterns = load_exclude_patterns(project_root) if project_root else None

    index = scip_pb2.Index()
    with open(scip_file, "rb") as f:
        raw = f.read()

    try:
        index.ParseFromString(raw)
    except Exception:
        raw = raw.replace(b"\xed\xa0\x80", b"___")
        raw = raw.replace(b"\xed\xa8\x80", b"___")
        raw = raw.replace(b"\xed\xb0\x80", b"___")
        raw = raw.replace(b"\xed\xbf\xbf", b"___")
        index.ParseFromString(raw)

    scip_run_dir = _detect_scip_run_dir(scip_file, project_root, index.metadata.project_root) if project_root else None

    def _normalize_scip_doc_path(doc_path: str) -> str:
        rel = doc_path.replace("\\", "/")
        if project_root and scip_run_dir:
            try:
                abs_path = scip_run_dir / rel
                rel = str(abs_path.relative_to(project_root)).replace("\\", "/")
            except ValueError:
                pass
        if rel.startswith("./"):
            rel = rel[2:]
        return rel

    parsed_data: Dict[str, Any] = {
        "metadata": {
            "project_root": index.metadata.project_root,
            "tool_name": index.metadata.tool_info.name,
            "tool_version": index.metadata.tool_info.version,
        },
        "symbols": {},
        "occurrences": [],
        "edges": [],
        "files": [],
        "diagnostics": [],
    }

    # Pre-seed from existing DB scip_id map for incremental fallback; Pass 0 overwrites with current workspace defs
    scip_to_canonical: Dict[str, str] = dict(existing_scip_map) if existing_scip_map else {}
    scip_to_leaf: Dict[str, str] = {}
    scip_to_derived_parent: Dict[str, Optional[str]] = {}
    canonical_to_raw_scip: Dict[str, str] = {}

    # Pass 0: Pre-index all workspace definitions across ALL included documents before resolving any references
    included_docs: List[Tuple[Any, str]] = []
    for document in index.documents:
        resolved_filepath = _normalize_scip_doc_path(document.relative_path)
        if is_excluded(resolved_filepath, exclude_patterns):
            continue
        if include_dirs and not is_included(resolved_filepath, include_dirs, exclude_patterns):
            continue
        included_docs.append((document, resolved_filepath))

        doc_kinds: Dict[str, str] = {}
        for sym_info in document.symbols:
            raw_sym = sym_info.symbol
            if not raw_sym or raw_sym.startswith("local "):
                continue
            k_str = _kind_name(sym_info.kind)
            doc_kinds[raw_sym] = k_str
            c_id, leaf_name, derived_p = scip_to_canonical_id(raw_sym, resolved_filepath=resolved_filepath, kind=k_str)
            scip_to_canonical[raw_sym] = c_id
            scip_to_leaf[raw_sym] = leaf_name
            scip_to_derived_parent[raw_sym] = derived_p
            canonical_to_raw_scip[c_id] = raw_sym

        for occ in document.occurrences:
            raw_sym = occ.symbol
            if not raw_sym or raw_sym.startswith("local ") or not (occ.symbol_roles & 1):
                continue
            if raw_sym not in scip_to_canonical or scip_to_canonical[raw_sym].startswith("ext::"):
                k_str = doc_kinds.get(raw_sym) or infer_scip_kind(raw_sym)
                c_id, leaf_name, derived_p = scip_to_canonical_id(raw_sym, resolved_filepath=resolved_filepath, kind=k_str)
                scip_to_canonical[raw_sym] = c_id
                scip_to_leaf[raw_sym] = leaf_name
                scip_to_derived_parent[raw_sym] = derived_p
                canonical_to_raw_scip[c_id] = raw_sym

    def resolve_canonical(raw_scip: str, kind: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
        if not raw_scip or raw_scip.startswith("local "):
            return raw_scip or "", raw_scip or "", None
        if raw_scip in scip_to_canonical:
            c_id = scip_to_canonical[raw_scip]
            leaf = scip_to_leaf.get(raw_scip) or parse_canonical_id(c_id)[2]
            return c_id, leaf, scip_to_derived_parent.get(raw_scip)
        # Not defined in any workspace document -> external symbol
        c_id, leaf, p_id = scip_to_canonical_id(raw_scip, resolved_filepath=None, kind=kind)
        scip_to_canonical[raw_scip] = c_id
        scip_to_leaf[raw_scip] = leaf
        scip_to_derived_parent[raw_scip] = p_id
        canonical_to_raw_scip[c_id] = raw_scip
        return c_id, leaf, p_id

    # Map external symbols (deferred ingestion: only emit if referenced by active occurrences/edges)
    external_symbols_map: Dict[str, Tuple[Any, str, Optional[str]]] = {}
    for sym_info in index.external_symbols:
        k_str = _kind_name(sym_info.kind)
        c_id, leaf, p_id = resolve_canonical(sym_info.symbol, kind=k_str)
        external_symbols_map[c_id] = (sym_info, leaf, p_id)

    seen_edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def add_edge(src: str, tgt: str, rel: str, line: Optional[int] = None):
        key = (src, tgt, rel)
        if key not in seen_edges:
            seen_edges[key] = {
                "source": src,
                "target": tgt,
                "relation": rel,
                "call_line": line,
            }
        elif line is not None:
            curr = seen_edges[key].get("call_line")
            if curr is None or line < curr:
                seen_edges[key]["call_line"] = line

    # Pass 1: Extract local symbol definitions, relationships, occurrences, and diagnostics
    active_docs: List[Tuple[Any, str]] = []
    for document, resolved_filepath in included_docs:
        if changed_set is not None and resolved_filepath not in changed_set:
            continue
        active_docs.append((document, resolved_filepath))
        parsed_data["files"].append(resolved_filepath)

        symbol_metadata: Dict[str, Dict[str, Any]] = {}
        for sym_info in document.symbols:
            raw_sym = sym_info.symbol
            if not raw_sym or raw_sym.startswith("local "):
                continue
            docs = "\n".join(sym_info.documentation) if sym_info.documentation else ""
            kind_str = _kind_name(sym_info.kind)
            c_id, leaf_name, derived_p = resolve_canonical(raw_sym, kind=kind_str)

            parent_sym = getattr(sym_info, "enclosing_symbol", None) or None
            if parent_sym:
                parent_canonical, _, _ = resolve_canonical(parent_sym)
            else:
                parent_canonical = derived_p

            symbol_metadata[raw_sym] = {
                "canonical_id": c_id,
                "name": leaf_name,
                "docs": docs,
                "kind": kind_str,
                "parent_symbol": parent_canonical,
            }

            for rel in getattr(sym_info, "relationships", []):
                tgt_can, _, _ = resolve_canonical(rel.symbol)
                if getattr(rel, "is_implementation", False):
                    add_edge(c_id, tgt_can, "Implements")
                if getattr(rel, "is_type_definition", False):
                    add_edge(c_id, tgt_can, "TypeDefinition")

        for occ in document.occurrences:
            raw_symbol = occ.symbol
            is_definition = bool(occ.symbol_roles & 1)

            r_tuple = normalize_range(occ, use_enclosing=is_definition)
            if not r_tuple:
                continue
            start_line, start_col, end_line, end_col = r_tuple

            if not is_definition and raw_symbol and not raw_symbol.startswith("local "):
                ref_can, _, _ = resolve_canonical(raw_symbol)
                parsed_data["occurrences"].append({
                    "symbol": ref_can,
                    "filepath": resolved_filepath,
                    "start_line": start_line + 1,
                    "start_col": start_col,
                    "end_line": end_line + 1,
                    "end_col": end_col,
                    "role": occ.symbol_roles,
                })

            for diag in getattr(occ, "diagnostics", []):
                sev_name = (
                    scip_pb2.Severity.Name(diag.severity)
                    if diag.severity in scip_pb2.Severity.values()
                    else str(diag.severity)
                )
                clean_sev = sev_name.replace("Severity", "") if sev_name.endswith("Severity") and len(sev_name) > 8 else sev_name
                tag_names = [
                    scip_pb2.DiagnosticTag.Name(t)
                    for t in getattr(diag, "tags", [])
                    if t in scip_pb2.DiagnosticTag.values() and t != 0
                ]
                diag_can = resolve_canonical(raw_symbol)[0] if (raw_symbol and not raw_symbol.startswith("local ")) else None
                parsed_data["diagnostics"].append({
                    "filepath": resolved_filepath,
                    "symbol": diag_can,
                    "line": start_line + 1,
                    "col": start_col,
                    "severity": clean_sev,
                    "code": diag.code or None,
                    "message": diag.message or "",
                    "tags": ",".join(tag_names) if tag_names else None,
                })

            if is_definition and raw_symbol and not raw_symbol.startswith("local "):
                meta = symbol_metadata.get(raw_symbol)
                if meta:
                    c_id = meta["canonical_id"]
                    leaf_name = meta["name"]
                    kind = meta["kind"]
                    parent_canonical = meta["parent_symbol"]
                    docs = meta["docs"]
                else:
                    kind = infer_scip_kind(raw_symbol)
                    c_id, leaf_name, parent_canonical = resolve_canonical(raw_symbol, kind=kind)
                    docs = ""

                new_candidate = {
                    "symbol": c_id,
                    "name": leaf_name,
                    "scip_id": raw_symbol,
                    "filepath": resolved_filepath,
                    "kind": kind,
                    "signature": None,
                    "docstring": docs,
                    "body_hash": None,
                    "start_line": start_line + 1,
                    "start_col": start_col,
                    "end_line": end_line + 1,
                    "end_col": end_col,
                    "parent_symbol": parent_canonical,
                }

                if c_id in parsed_data["symbols"]:
                    existing = parsed_data["symbols"][c_id]
                    if score_definition_candidate(
                        new_candidate,
                        filepath=resolved_filepath,
                        start_line=start_line + 1,
                        end_line=end_line + 1,
                    ) > score_definition_candidate(
                        existing,
                        filepath=existing.get("filepath"),
                        start_line=existing.get("start_line", 1),
                        end_line=existing.get("end_line", 1),
                    ):
                        parsed_data["symbols"][c_id] = new_candidate
                else:
                    parsed_data["symbols"][c_id] = new_candidate

    # Pass 2: Widen collapsed 1-line SCIP definition spans via Tree-sitter AST and extract Calls edges
    ast_span_cache: Dict[str, List[Tuple[int, int, str]]] = dict(ast_spans_by_file) if ast_spans_by_file else {}
    occurrences_by_file: Dict[str, List[Dict[str, Any]]] = {}

    for sym, sym_data in parsed_data["symbols"].items():
        scip_id = sym_data.get("scip_id") or ""
        kind = sym_data.get("kind") or ""
        if kind in ("Parameter", "TypeParameter") or scip_id.endswith(")") or (scip_id.endswith(".") and not scip_id.endswith("().")):
            continue
        fp = sym_data.get("filepath")
        if fp:
            s_line = sym_data.get("start_line", 1)
            e_line = sym_data.get("end_line", s_line)
            if s_line == e_line and project_root:
                if fp not in ast_span_cache:
                    full_fp = project_root / fp if not Path(fp).is_absolute() else Path(fp)
                    if full_fp.exists():
                        try:
                            from engines.treesitter.extractor import extract_symbols_from_file
                            ast_decls = extract_symbols_from_file(full_fp, project_root=project_root)
                            ast_span_cache[fp] = [
                                (d.start_line, d.end_line, d.name) for d in ast_decls if d.start_line < d.end_line
                            ]
                        except Exception:
                            logger.debug("Failed to widen AST spans for %s", fp, exc_info=True)
                            ast_span_cache[fp] = []
                    else:
                        ast_span_cache[fp] = []

                for ast_s, ast_e, _ in ast_span_cache.get(fp, []):
                    if ast_s == s_line and ast_e > e_line:
                        sym_data["end_line"] = ast_e
                        break

            occurrences_by_file.setdefault(fp, []).append(sym_data)

    for defs in occurrences_by_file.values():
        defs.sort(key=lambda d: d["end_line"] - d["start_line"])

    for document, resolved_filepath in active_docs:
        file_defs = occurrences_by_file.get(resolved_filepath, [])
        for occ in document.occurrences:
            raw_symbol = occ.symbol
            is_reference = not bool(occ.symbol_roles & 1)
            if not is_reference or not raw_symbol or raw_symbol.startswith("local ") or raw_symbol.endswith(")"):
                continue

            r_tuple = normalize_range(occ)
            if not r_tuple:
                continue
            ref_line = r_tuple[0] + 1

            caller_symbol = None
            for def_occ in file_defs:
                if def_occ["start_line"] <= ref_line <= def_occ["end_line"]:
                    caller_symbol = def_occ["symbol"]
                    break

            if caller_symbol:
                target_can, _, _ = resolve_canonical(raw_symbol)
                if caller_symbol != target_can and not caller_symbol.startswith("local ") and not target_can.startswith("local "):
                    add_edge(caller_symbol, target_can, "Calls", ref_line)

    parsed_data["edges"] = list(seen_edges.values())

    # Pass 3: Synthesize referenced external / cross-file symbols absent from parsed_data["symbols"]
    referenced_syms: Set[str] = set()
    for occ in parsed_data["occurrences"]:
        if occ.get("symbol") and not occ["symbol"].startswith("local "):
            referenced_syms.add(occ["symbol"])
    for edge in parsed_data["edges"]:
        if edge.get("source") and not edge["source"].startswith("local "):
            referenced_syms.add(edge["source"])
        if edge.get("target") and not edge["target"].startswith("local "):
            referenced_syms.add(edge["target"])

    for sym in referenced_syms:
        if sym in parsed_data["symbols"]:
            continue
        if sym in external_symbols_map:
            sym_info, leaf, p_id = external_symbols_map[sym]
            docs = "\n".join(sym_info.documentation) if sym_info.documentation else ""
            parsed_data["symbols"][sym] = {
                "symbol": sym,
                "name": leaf,
                "scip_id": sym_info.symbol,
                "filepath": None,
                "kind": _kind_name(sym_info.kind),
                "signature": None,
                "docstring": docs,
                "body_hash": None,
                "start_line": 1,
                "end_line": 1,
                "parent_symbol": p_id,
            }
        else:
            raw_scip = canonical_to_raw_scip.get(sym)
            _, _, leaf = parse_canonical_id(sym)
            parsed_data["symbols"][sym] = {
                "symbol": sym,
                "name": leaf or sym,
                "scip_id": raw_scip,
                "filepath": None,
                "kind": infer_scip_kind(raw_scip) if raw_scip else "Symbol",
                "signature": None,
                "docstring": "",
                "body_hash": None,
                "start_line": 1,
                "end_line": 1,
                "parent_symbol": scip_to_derived_parent.get(raw_scip) if raw_scip else None,
            }

    return parsed_data
