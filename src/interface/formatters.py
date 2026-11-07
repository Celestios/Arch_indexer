from typing import Any, Dict, List, Optional, Tuple
from utils.helpers import demangle_scip_symbol, sanitize_docstring, infer_scip_kind


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

        sym_data = {
            "symbol": clean_name,
            "signature": sym["signature"],
            "docstring": sanitize_docstring(sym["docstring"]),
            "line_range": line_range,
            "kind": kind,
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
            md.append(f"- **{cl['symbol']}**{range_str} ({cl['kind']})")
            doc = _clean_doc_summary(cl["docstring"])
            if doc:
                md.append(f"  * {doc}")
        md.append("")

    if methods_and_funcs:
        md.append("### Methods & Functions")
        for mf in methods_and_funcs:
            range_str = f" [{mf['line_range']}]" if mf["line_range"] else ""
            md.append(f"- **{mf['symbol']}**{range_str}")
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
) -> str:
    """Format lookup results for a code symbol as markdown."""
    clean_symbol = demangle_scip_symbol(exact_symbol[0])
    md = []
    md.append(f"## Code Symbol: `{clean_symbol}`\n")
    md.append(f"- **Filepath**: `{exact_symbol[1] or 'External / Third-party'}`")
    md.append(f"- **Kind**: `{exact_symbol[2]}`")
    md.append(f"- **Signature**: `{exact_symbol[3] or 'None'}`")
    doc = sanitize_docstring(exact_symbol[4]).strip() if exact_symbol[4] else "No docstring available."
    md.append(f"- **Docstring**:\n  {doc.replace(chr(10), chr(10) + '  ')}\n")

    if occurrences:
        md.append("### Symbol Occurrences")
        md.append("| Filepath | Line Range | Role (Definition=1, Ref=2) |")
        md.append("| :--- | :--- | :--- |")
        seen_occ = set()
        for o in occurrences:
            role_label = "Definition" if (o[3] & 1) else "Reference"
            line_str = f"L{o[1]}" if o[1] == o[2] else f"L{o[1]}-{o[2]}"
            norm_fp = str(o[0]).replace("\\", "/")
            occ_key = (norm_fp, line_str, role_label)
            if occ_key in seen_occ:
                continue
            seen_occ.add(occ_key)
            md.append(f"| `{norm_fp}` | {line_str} | {role_label} |")
        md.append("")

    # Filter out local edges
    clean_edges = [e for e in edges if not str(e[0]).startswith("local ") and not str(e[1]).startswith("local ")]
    if clean_edges:
        md.append("### Call Graph Relationships")
        md.append("| Source (Caller) | Target (Callee) | Relation |")
        md.append("| :--- | :--- | :--- |")
        for e in clean_edges:
            src = demangle_scip_symbol(e[0])
            tgt = demangle_scip_symbol(e[1])
            md.append(f"| `{src}` | `{tgt}` | `{e[2]}` |")
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

