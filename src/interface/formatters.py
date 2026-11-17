from typing import Any, Dict, List, Optional, Tuple
from utils.helpers import demangle_scip_symbol, sanitize_docstring, infer_scip_kind, format_classification_badge


def _clean_doc_summary(doc: Optional[str]) -> str:
    """Extract a meaningful single-line summary from docstrings, skipping code fences, type annotations, and signatures."""
    if not doc:
        return ""
    lines = [line.strip() for line in doc.strip().split("\n")]
    in_fence = False
    fence_char = None
    real_lines = []
    for l in lines:
        if not l:
            continue
        if l.startswith("```") or l.startswith("'''") or l.startswith('"""'):
            tag = l[:3]
            if not in_fence:
                in_fence = True
                fence_char = tag
                if len(l) > 3 and l.endswith(tag):
                    in_fence = False
                continue
            elif in_fence and tag == fence_char:
                in_fence = False
                continue
        if in_fence:
            continue
        real_lines.append(l)

    if not real_lines:
        return ""

    candidate = real_lines[0]
    # Filter out fake docstrings that echo definition or SCIP type hints
    if candidate.startswith("def ") or candidate.startswith("class ") or candidate.endswith(":"):
        return ""
    if candidate.startswith("(variable)") or candidate.startswith("(function)") or candidate.startswith("(method)"):
        return ""
    if candidate in ("builtins.str", "builtins.int", "builtins.dict", "builtins.list", "builtins.bool", "pathlib.Path"):
        return ""
    if candidate.startswith("builtins.") or candidate.startswith("pathlib.") or candidate.startswith("typing."):
        return ""
    if candidate.endswith("(") or candidate.endswith("()"):
        return ""
    return candidate


def _clean_method_signature(sig: str, name: str) -> str:
    """Extract a clean, single-line method signature."""
    if not sig:
        return f"{name}()"
    lines = [l.strip() for l in sig.strip().split("\n") if l.strip()]
    if not lines:
        return f"{name}()"

    decorators = [l for l in lines if l.startswith("@")]
    def_lines = [l for l in lines if not l.startswith("@")]

    dec_prefix = " ".join(decorators) + " " if decorators else ""
    def_str = def_lines[0] if def_lines else f"def {name}()"

    if def_str.endswith(":"):
        def_str = def_str[:-1].strip()

    combined = f"{dec_prefix}{def_str}".strip()

    clean_base = name.split("(")[0].strip()
    if clean_base and clean_base not in combined:
        return f"`{name}`: `{combined}`"

    return f"`{combined}`"


def format_context_results(
    fp: str,
    symbols: List[Dict[str, Any]],
    symbol_to_lines: Dict[str, Tuple[int, int]],
) -> str:
    """Format context results for a single file as markdown with clean tree hierarchy."""
    if not symbols:
        return f"## File Index: `{fp}`\n\n*No indexed symbols found in file. Make sure the file exists and is indexed.*"

    processed_symbols = []
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
        doc = _clean_doc_summary(sym.get("docstring"))

        processed_symbols.append({
            "raw_name": raw_name,
            "clean_name": clean_name,
            "kind": kind,
            "signature": sym.get("signature") or "",
            "docstring": doc,
            "line_range": line_range,
            "badge": badge,
            "parent_symbol": sym.get("parent_symbol"),
        })

    classes = []
    class_map = {}
    non_classes = []

    for s in processed_symbols:
        if s["kind"].lower() in ("class", "struct", "interface"):
            cl_data = {
                **s,
                "short_name": s["clean_name"].split(".")[-1],
                "methods": [],
                "fields": [],
            }
            classes.append(cl_data)
            class_map[s["clean_name"]] = cl_data
            class_map[s["raw_name"]] = cl_data
        else:
            non_classes.append(s)

    top_level_funcs = []
    top_level_vars = []

    for s in non_classes:
        parent_class = None

        if s["parent_symbol"]:
            p_clean = demangle_scip_symbol(s["parent_symbol"])
            if p_clean in class_map:
                parent_class = class_map[p_clean]
            elif s["parent_symbol"] in class_map:
                parent_class = class_map[s["parent_symbol"]]

        if not parent_class:
            for cl in classes:
                prefix = cl["clean_name"] + "."
                if s["clean_name"].startswith(prefix):
                    parent_class = cl
                    break

        if not parent_class and "#" in s["raw_name"]:
            scip_prefix = s["raw_name"].split("#")[0] + "#"
            if scip_prefix in class_map:
                parent_class = class_map[scip_prefix]

        is_func = (
            s["kind"].lower() in ("method", "function", "constructor")
            or s["raw_name"].endswith(")")
            or s["signature"].strip().startswith("def ")
            or s["signature"].strip().startswith("@")
        )

        if parent_class:
            prefix = parent_class["clean_name"] + "."
            if s["clean_name"].startswith(prefix):
                s["short_name"] = s["clean_name"][len(prefix):]
            else:
                s["short_name"] = s["clean_name"].split(".")[-1]

            if is_func:
                parent_class["methods"].append(s)
            else:
                parent_class["fields"].append(s)
        else:
            s["short_name"] = s["clean_name"].split(".")[-1]
            if is_func:
                top_level_funcs.append(s)
            else:
                top_level_vars.append(s)

    md = [f"## File Index: `{fp}`\n"]

    if top_level_vars:
        md.append("### Constants & Variables")
        for v in top_level_vars:
            range_str = f" [{v['line_range']}]" if v["line_range"] else ""
            badge_str = f" `{v['badge']}`" if v.get("badge") else ""
            sig = v["signature"].strip()
            if sig and "\n" not in sig and "=" in sig:
                val = sig.split("=", 1)[1].strip()
                if len(val) > 60:
                    val = val[:57] + "..."
                md.append(f"- `{v['short_name']}`{badge_str}{range_str} = `{val}`")
            elif sig and "\n" not in sig and not sig.startswith("self."):
                md.append(f"- `{v['short_name']}`{badge_str}{range_str}: `{sig}`")
            else:
                md.append(f"- `{v['short_name']}`{badge_str}{range_str}")
            if v["docstring"]:
                md.append(f"  * {v['docstring']}")
        md.append("")

    if classes:
        md.append("### Classes")
        for cl in classes:
            range_str = f" [{cl['line_range']}]" if cl["line_range"] else ""
            badge_str = f" `{cl['badge']}`" if cl.get("badge") else ""
            kind_label = cl["kind"].lower()
            if kind_label in ("class", "struct", "interface"):
                header_title = f"{kind_label} {cl['short_name']}"
            else:
                header_title = f"{cl['short_name']} ({cl['kind']})"
            md.append(f"- **{header_title}**{badge_str}{range_str}")

            if cl["docstring"]:
                md.append(f"  * *Docstring*: {cl['docstring']}")

            if cl["fields"]:
                field_strs = []
                for f in cl["fields"]:
                    frange = f" [{f['line_range']}]" if f["line_range"] else ""
                    fsig = f["signature"].strip()
                    if fsig.startswith("self."):
                        fsig = fsig[5:].strip()
                    if fsig and "\n" not in fsig and len(fsig) <= 40:
                        field_strs.append(f"`{fsig}`{frange}")
                    else:
                        field_strs.append(f"`{f['short_name']}`{frange}")
                md.append(f"  * *Fields*: {', '.join(field_strs)}")

            if cl["methods"]:
                md.append("  * *Methods*:")
                for m in cl["methods"]:
                    mrange = f" [{m['line_range']}]" if m["line_range"] else ""
                    mbadge = f" `{m['badge']}`" if m.get("badge") else ""
                    msig = _clean_method_signature(m["signature"], m["short_name"])
                    md.append(f"    - {msig}{mbadge}{mrange}")
                    if m["docstring"]:
                        md.append(f"      * {m['docstring']}")
        md.append("")

    if top_level_funcs:
        section_name = "### Functions" if classes else "### Methods & Functions"
        md.append(section_name)
        for fn in top_level_funcs:
            range_str = f" [{fn['line_range']}]" if fn["line_range"] else ""
            badge_str = f" `{fn['badge']}`" if fn.get("badge") else ""
            fsig = _clean_method_signature(fn["signature"], fn["short_name"])
            md.append(f"- {fsig}{badge_str}{range_str}")
            if fn["docstring"]:
                md.append(f"  * {fn['docstring']}")
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

