from typing import Any, Dict, List, Optional, Tuple
from utils.helpers import demangle_scip_symbol, sanitize_docstring, infer_scip_kind, format_classification_badge


def _clean_doc_summary(doc: Optional[str]) -> str:
    """Extract a meaningful single-line summary from docstrings, skipping code fences and signatures."""
    if not doc:
        return ""
    lines = [line.strip() for line in doc.strip().split("\n")]
    in_fence = False
    fence_char = None
    for l in lines:
        if not l:
            continue
        if l.startswith("```") or l.startswith("'''") or l.startswith('"""'):
            tag = l[:3]
            if not in_fence:
                in_fence = True
                fence_char = tag
                # Check if closed on same line (e.g. ```text```)
                if len(l) > 3 and l.endswith(tag):
                    in_fence = False
                continue
            elif in_fence and tag == fence_char:
                in_fence = False
                continue
        if in_fence:
            continue
        if l.startswith("class ") or l.startswith("def ") or l.endswith(":"):
            continue
        return l
    # Fallback if everything was inside a fence
    content_lines = [l for l in lines if l and not l.startswith("```") and not l.startswith("'''") and not l.startswith('"""')]
    return content_lines[0] if content_lines else ""


def format_context_results(
    fp: str,
    symbols: List[Dict[str, Any]],
    symbol_to_lines: Dict[str, Tuple[int, int]],
) -> str:
    """Format context results for a single file as markdown."""
    if not symbols:
        return f"## File Index: `{fp}`\n\n*No indexed symbols found in file. Make sure the file exists and is indexed.*"

    classes = []
    methods_and_funcs = []

    for sym in symbols:
        raw_name = sym["symbol"]
        if raw_name.startswith("local "):
            continue

        kind = sym.get("kind", "UnspecifiedKind")
        if kind == "UnspecifiedKind" or not kind or (raw_name.endswith(")") and not raw_name.endswith("()")):
            kind = infer_scip_kind(raw_name)

        if kind.lower() in ("module", "package", "parameter") or raw_name.endswith("/__init__:") or raw_name.endswith("/"):
            continue

        clean_name = demangle_scip_symbol(raw_name)

        line_range = ""
        if raw_name in symbol_to_lines:
            start_line, end_line = symbol_to_lines[raw_name]
            line_range = f"L{start_line}-{end_line}" if start_line != end_line else f"L{start_line}"
        elif clean_name in symbol_to_lines:
            start_line, end_line = symbol_to_lines[clean_name]
            line_range = f"L{start_line}-{end_line}" if start_line != end_line else f"L{start_line}"

        badge = format_classification_badge(sym.get("classification"))
        sym_data = {
            "symbol": clean_name,
            "signature": sym["signature"],
            "docstring": sanitize_docstring(sym["docstring"]),
            "line_range": line_range,
            "kind": kind,
            "badge": badge,
        }

        if kind.lower() in ("class", "struct", "interface"):
            classes.append(sym_data)
        elif kind.lower() in ("field", "variable") and not sym.get("signature"):
            continue
        else:
            methods_and_funcs.append(sym_data)

    md = [f"## File Index: `{fp}`\n"]

    if classes:
        md.append("### Classes")
        for cl in classes:
            range_str = f" [{cl['line_range']}]" if cl["line_range"] else ""
            badge_str = f" `{cl['badge']}`" if cl.get("badge") else ""
            md.append(f"- **{cl['symbol']}**{badge_str}{range_str} ({cl['kind']})")
            doc = _clean_doc_summary(cl["docstring"])
            if doc:
                md.append(f"  * {doc}")
        md.append("")

    if methods_and_funcs:
        md.append("### Methods & Functions")
        for mf in methods_and_funcs:
            range_str = f" [{mf['line_range']}]" if mf["line_range"] else ""
            badge_str = f" `{mf['badge']}`" if mf.get("badge") else ""
            md.append(f"- **{mf['symbol']}**{badge_str}{range_str}")
            if mf["signature"]:
                md.append(f"  * *Signature*: `{mf['signature']}`")
            doc = _clean_doc_summary(mf["docstring"])
            if doc:
                md.append(f"  * *Docstring*: {doc}")
        md.append("")

    return "\n".join(md)


def format_lookup_symbol(
    exact_symbol: tuple,
    occurrences: List[tuple],
    edges: List[tuple],
    symbol_filepath_map: Optional[Dict[str, str]] = None,
) -> str:
    """Format lookup results for a code symbol as markdown with unified references and call graph."""
    clean_symbol = exact_symbol[10] if len(exact_symbol) > 10 and exact_symbol[10] else demangle_scip_symbol(exact_symbol[0])
    raw_symbol = str(exact_symbol[0])
    badge = ""
    if len(exact_symbol) > 8 and exact_symbol[8]:
        badge = format_classification_badge(exact_symbol[8])
    badge_header = f" `{badge}`" if badge else ""

    md = []
    md.append(f"## Code Symbol: `{clean_symbol}`{badge_header}\n")
    md.append(f"- **Filepath**: `{exact_symbol[1] or 'External / Third-party'}`")
    md.append(f"- **Kind**: `{exact_symbol[2]}`")
    md.append(f"- **Signature**: `{exact_symbol[3] or 'None'}`")
    if badge:
        md.append(f"- **Classification**: `{badge}`")
    if len(exact_symbol) > 7 and exact_symbol[7]:
        parent_clean = demangle_scip_symbol(exact_symbol[7])
        md.append(f"- **Enclosing Symbol**: `{parent_clean}`")
    if len(exact_symbol) > 9 and exact_symbol[9] is not None:
        cnt = exact_symbol[9]
        churn_str = f"⚡ High Churn ({cnt} modifications)" if cnt >= 3 else f"Stable ({cnt} edits)"
        md.append(f"- **Stability**: {churn_str}")
    doc = sanitize_docstring(exact_symbol[4]).strip() if exact_symbol[4] else "No docstring available."
    md.append(f"- **Docstring**:\n  {doc.replace(chr(10), chr(10) + '  ')}\n")

    # Group occurrences by normalized filepath
    file_occs: Dict[str, Dict[str, Any]] = {}
    for o in (occurrences or []):
        norm_fp = str(o[0]).replace("\\", "/")
        s_line, e_line, role = o[1], o[2], o[3]
        if norm_fp not in file_occs:
            file_occs[norm_fp] = {"lines": [], "roles": set(), "has_def": False}
        file_occs[norm_fp]["lines"].append((s_line, e_line))
        if role & 1:
            file_occs[norm_fp]["has_def"] = True
            file_occs[norm_fp]["roles"].add("Definition")
        else:
            file_occs[norm_fp]["roles"].add("Reference")
        if role & 4:
            file_occs[norm_fp]["roles"].add("[Mutates]")
        if role & 8:
            file_occs[norm_fp]["roles"].add("[Reads]")
        if role & 0x20:
            file_occs[norm_fp]["roles"].add("[Test]")

    def _format_lines(line_tuples: List[Tuple[int, int]]) -> str:
        unique_ranges = []
        for s, e in sorted(line_tuples, key=lambda x: (x[0], x[1])):
            l_str = f"L{s}" if s == e else f"L{s}-{e}"
            if l_str not in unique_ranges:
                unique_ranges.append(l_str)
        return ", ".join(unique_ranges)

    def _format_roles(role_set: set) -> str:
        if "Definition" in role_set and len(role_set) == 1:
            return "Definition"
        is_ref = "Reference" in role_set or not role_set
        tags = []
        if "[Mutates]" in role_set:
            tags.append("[Mutates]")
        if "[Reads]" in role_set:
            tags.append("[Reads]")
        if "[Test]" in role_set:
            tags.append("[Test]")
        if "Definition" in role_set:
            tags.append("[Def]")
        tag_str = " ".join(tags)
        if is_ref:
            return f"Reference {tag_str}".strip()
        return tag_str if tag_str else "Reference"

    # Filter out local edges and group edges by (related_symbol, direction)
    clean_edges = [e for e in (edges or []) if not str(e[0]).startswith("local ") and not str(e[1]).startswith("local ")]
    sym_edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in clean_edges:
        src_raw = str(e[0])
        tgt_raw = str(e[1])
        rel = str(e[2])

        # Determine direction relative to queried symbol
        if tgt_raw == raw_symbol or demangle_scip_symbol(tgt_raw) == clean_symbol:
            direction = "←"
            rel_raw = src_raw
        elif src_raw == raw_symbol or demangle_scip_symbol(src_raw) == clean_symbol:
            direction = "→"
            rel_raw = tgt_raw
        else:
            direction = "←"
            rel_raw = src_raw

        rel_clean = demangle_scip_symbol(rel_raw)
        key = (rel_raw, direction)
        if key not in sym_edges:
            fp = None
            if symbol_filepath_map and rel_raw in symbol_filepath_map:
                fp = symbol_filepath_map[rel_raw]
            elif symbol_filepath_map and rel_clean in symbol_filepath_map:
                fp = symbol_filepath_map[rel_clean]
            elif rel_raw.replace("\\", "/") in file_occs:
                fp = rel_raw.replace("\\", "/")
            else:
                # Heuristic match against occurrence file stems
                for ofp in file_occs:
                    stem = ofp.rsplit("/", 1)[-1].split(".", 1)[0]
                    if stem and stem in rel_clean.split("."):
                        fp = ofp
                        break

            sym_edges[key] = {
                "raw": rel_raw,
                "clean": rel_clean,
                "direction": direction,
                "relations": set(),
                "fp": fp.replace("\\", "/") if fp else None,
            }
        sym_edges[key]["relations"].add(rel)

    def _display_sym(rel_clean: str, fp: Optional[str]) -> str:
        if not fp:
            return rel_clean
        stem = fp.rsplit("/", 1)[-1].split(".", 1)[0]
        parts = rel_clean.split(".")
        if stem in parts:
            idx = parts.index(stem)
            subparts = parts[idx + 1:]
            if subparts:
                return ".".join(subparts)
        return rel_clean

    matched_files = set()
    table_rows = []

    # 1. Definition row if occurrences contain definition
    for fp, occ_data in file_occs.items():
        if occ_data["has_def"]:
            matched_files.add(fp)
            lines_str = _format_lines(occ_data["lines"])
            loc = f"`{fp}:{lines_str}`"
            table_rows.append({
                "loc": loc,
                "sym": f"`{clean_symbol}`",
                "rel": "—",
                "role": "Definition",
                "order": (0, fp, clean_symbol)
            })

    # 2. Correlated or standalone edges
    for (rel_raw, direction), data in sym_edges.items():
        fp = data["fp"]
        rel_str = f"{direction} {', '.join(sorted(data['relations']))}"
        sym_label = f"`{_display_sym(data['clean'], fp)}`"

        if fp and fp in file_occs:
            matched_files.add(fp)
            lines_str = _format_lines(file_occs[fp]["lines"])
            loc = f"`{fp}:{lines_str}`"
            role_str = _format_roles(file_occs[fp]["roles"])
            table_rows.append({
                "loc": loc,
                "sym": sym_label,
                "rel": rel_str,
                "role": role_str,
                "order": (1, fp, data["clean"])
            })
        else:
            loc = f"`{fp}`" if fp else "—"
            table_rows.append({
                "loc": loc,
                "sym": sym_label,
                "rel": rel_str,
                "role": "—",
                "order": (2, fp or "zzz", data["clean"])
            })

    # 3. Remaining file occurrences without graph edges
    for fp, occ_data in file_occs.items():
        if fp in matched_files:
            continue
        lines_str = _format_lines(occ_data["lines"])
        loc = f"`{fp}:{lines_str}`"
        role_str = _format_roles(occ_data["roles"])
        table_rows.append({
            "loc": loc,
            "sym": "—",
            "rel": "—",
            "role": role_str,
            "order": (3, fp, "")
        })

    if table_rows:
        table_rows.sort(key=lambda r: r["order"])
        md.append("### References & Call Graph")
        md.append("| Location | Symbol / Scope | Relation | Role |")
        md.append("| :--- | :--- | :--- | :--- |")
        for r in table_rows:
            md.append(f"| {r['loc']} | {r['sym']} | {r['rel']} | {r['role']} |")
        md.append("")

    return "\n".join(md)


def format_lookup_file(
    exact_file: tuple,
    file_symbols: List[tuple],
) -> str:
    """Format lookup results for a file module as markdown."""
    md = []
    status = exact_file[4].replace("VIOLATION_DETECTED", "VIOLATION") if exact_file[4] else ""
    md.append(f"## File Module: `{exact_file[0]}`\n")
    md.append(f"- **Status**: `{status}`")
    md.append(f"- **Justification**: *{exact_file[8] or 'None'}*")
    if exact_file[7] and exact_file[7] != "{}":
        md.append(f"- **Manual Fields**: `{exact_file[7]}`")
    md.append("")

    # Filter out local symbols
    non_local_symbols = [s for s in file_symbols if not str(s[0]).startswith("local ")]
    if non_local_symbols:
        md.append("### Symbols Declared in File")
        md.append("| Symbol | Kind |")
        md.append("| :--- | :--- |")
        for s in non_local_symbols:
            clean_s = demangle_scip_symbol(s[0])
            kind = infer_scip_kind(s[0]) if s[1] == "UnspecifiedKind" else s[1]
            md.append(f"| `{clean_s}` | {kind} |")
        md.append("")

    return "\n".join(md)

