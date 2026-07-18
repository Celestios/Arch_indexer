from typing import Any, Dict, List, Optional, Tuple


def _infer_kind(sym_name: str) -> str:
    """Infer symbol kind from its name."""
    name = sym_name.rsplit("/", 1)[-1] if "/" in sym_name else sym_name
    if name.endswith("#") or name.endswith("#."):
        return "Class"
    if name.endswith("()") or name.endswith(".()"):
        return "Function"
    if ".__init__()" in name or ".constructor()" in name:
        return "Constructor"
    if "." in name and not name.endswith("#"):
        return "Method"
    return "Symbol"


def format_query_results(
    q: str,
    keyword_symbols: List[tuple],
    file_matches: List[tuple],
    semantic_results: List[Dict[str, Any]],
) -> str:
    """Format query search results for a single query as markdown."""
    md = []
    md.append(f'## Search Results for: "{q}"\n')

    md.append("### 1. Symbol Name Matches (Keyword Search)")
    if not keyword_symbols:
        md.append("*No matching symbols found by name.*\n")
    else:
        for idx, row in enumerate(keyword_symbols, 1):
            md.append(f"{idx}. **{row[0]}**")
            if row[3]:
                md.append(f"   - **Signature**: `{row[3]}`")
        md.append("")

    md.append("### 2. Semantic Docstring Matches")
    if not semantic_results:
        md.append("*No semantically matching symbols found in docstrings.*\n")
    else:
        for idx, res in enumerate(semantic_results, 1):
            md.append(f"{idx}. **{res['symbol']}** (Similarity: {res['similarity']:.2f})")
            md.append(f"   - **File**: `{res['filepath']}`")
            md.append(f"   - **Kind**: `{res['kind']}`")
            if res["docstring"]:
                doc = res["docstring"].strip().replace("\n", "\n     ")
                md.append(f"   - **Doc**: {doc}")
        md.append("")

    md.append("### 3. Filepath Matches")
    if not file_matches:
        md.append("*No matching files found by path.*\n")
    else:
        for idx, row in enumerate(file_matches, 1):
            md.append(f"{idx}. **{row[0]}**")
            md.append(f"   - **Language**: `{row[1]}`")
            md.append(f"   - **Audit Status**: `{row[2]}`")
        md.append("")

    return "\n".join(md)


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
        sym_name = sym["symbol"]
        line_range = ""
        if sym_name in symbol_to_lines:
            start_line, end_line = symbol_to_lines[sym_name]
            line_range = f"L{start_line}-{end_line}"

        sym_data = {
            "symbol": sym_name,
            "signature": sym["signature"],
            "docstring": sym["docstring"],
            "line_range": line_range,
            "kind": sym["kind"],
        }

        if sym["kind"].lower() in ("class", "struct", "interface"):
            classes.append(sym_data)
        else:
            methods_and_funcs.append(sym_data)

    md = [f"## File Index: `{fp}`\n"]

    if classes:
        md.append("### Classes")
        for cl in classes:
            range_str = f" [{cl['line_range']}]" if cl["line_range"] else ""
            md.append(f"- **{cl['symbol']}**{range_str} ({cl['kind']})")
            if cl["docstring"]:
                doc = cl["docstring"].strip().split("\n")[0]
                md.append(f"  * {doc}")
        md.append("")

    if methods_and_funcs:
        md.append("### Methods & Functions")
        for mf in methods_and_funcs:
            range_str = f" [{mf['line_range']}]" if mf["line_range"] else ""
            md.append(f"- **{mf['symbol']}**{range_str}")
            if mf["signature"]:
                md.append(f"  * *Signature*: `{mf['signature']}`")
            if mf["docstring"]:
                doc = mf["docstring"].strip().split("\n")[0]
                md.append(f"  * *Docstring*: {doc}")
        md.append("")

    return "\n".join(md)


def format_lookup_symbol(
    exact_symbol: tuple,
    occurrences: List[tuple],
    edges: List[tuple],
) -> str:
    """Format lookup results for a code symbol as markdown."""
    md = []
    md.append(f"## Code Symbol: `{exact_symbol[0]}`\n")
    md.append(f"- **Filepath**: `{exact_symbol[1] or 'External / Third-party'}`")
    md.append(f"- **Kind**: `{exact_symbol[2]}`")
    md.append(f"- **Signature**: `{exact_symbol[3] or 'None'}`")
    doc = exact_symbol[4].strip() if exact_symbol[4] else "No docstring available."
    md.append(f"- **Docstring**:\n  {doc.replace(chr(10), chr(10) + '  ')}\n")

    if occurrences:
        md.append("### Symbol Occurrences")
        md.append("| Filepath | Line Range | Role (Definition=1, Ref=2) |")
        md.append("| :--- | :--- | :--- |")
        for o in occurrences:
            role_map = {0: "Reference", 1: "Definition", 2: "Declaration"}
            role_label = role_map.get(o[3], f"Unknown ({o[3]})")
            line_str = f"L{o[1]}" if o[1] == o[2] else f"L{o[1]}-{o[2]}"
            md.append(f"| `{o[0]}` | {line_str} | {role_label} |")
        md.append("")

    if edges:
        md.append("### Call Graph Relationships")
        md.append("| Source (Caller) | Target (Callee) | Relation |")
        md.append("| :--- | :--- | :--- |")
        for e in edges:
            md.append(f"| `{e[0]}` | `{e[1]}` | `{e[2]}` |")
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

    if file_symbols:
        md.append("### Symbols Declared in File")
        md.append("| Symbol | Kind |")
        md.append("| :--- | :--- |")
        for s in file_symbols:
            kind = _infer_kind(s[0]) if s[1] == "UnspecifiedKind" else s[1]
            md.append(f"| `{s[0]}` | {kind} |")
        md.append("")

    return "\n".join(md)
