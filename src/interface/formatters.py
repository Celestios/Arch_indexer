import json
from typing import Any, Dict, List, Optional, Tuple

from utils.helpers import format_classification_badge, sanitize_docstring
from utils.symbol_id import canonical_display_name, parse_canonical_id


def _clean_doc_summary(doc: Optional[str]) -> str:
    """Extract a meaningful single-line summary from docstrings, skipping code fences, type annotations, and signatures."""
    if not doc:
        return ""
    lines = [line.strip() for line in doc.strip().split("\n")]
    in_fence = False
    fence_char = None
    real_lines = []
    for line in lines:
        if not line:
            continue
        if line.startswith("```") or line.startswith("\'\'\'") or line.startswith('"""'):
            tag = line[:3]
            if not in_fence:
                in_fence = True
                fence_char = tag
                if len(line) > 3 and line.endswith(tag):
                    in_fence = False
                continue
            elif in_fence and tag == fence_char:
                in_fence = False
                continue
        if in_fence:
            continue
        real_lines.append(line)

    if not real_lines:
        return ""

    candidate = real_lines[0]
    if candidate.startswith(("def ", "class ")) or candidate.endswith(":"):
        return ""
    if candidate.startswith(("(variable)", "(function)", "(method)")):
        return ""
    if candidate.startswith(("builtins.", "pathlib.", "typing.")):
        return ""
    if candidate.endswith(("(", "()")):
        return ""
    return candidate


def _clean_method_signature(sig: str, name: str) -> str:
    """Extract a clean, single-line method signature."""
    if not sig:
        return f"`{name}()`"
    lines = [l.strip() for l in sig.strip().split("\n") if l.strip()]
    if not lines:
        return f"`{name}()`"

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
        raw_id = sym["symbol"]
        if raw_id.startswith("local "):
            continue

        kind = sym.get("kind") or "Symbol"
        if kind.lower() in ("module", "package", "parameter", "typeparameter"):
            continue

        leaf_name = sym.get("name") or parse_canonical_id(raw_id)[2]
        disp_name = canonical_display_name(raw_id, leaf_name)

        line_range = ""
        if raw_id in symbol_to_lines:
            start_line, end_line = symbol_to_lines[raw_id]
            line_range = f"L{start_line}-{end_line}" if start_line != end_line else f"L{start_line}"

        badge = format_classification_badge(sym.get("classification"))
        doc = _clean_doc_summary(sym.get("docstring"))

        processed_symbols.append({
            "raw_id": raw_id,
            "name": leaf_name,
            "display_name": disp_name,
            "kind": kind,
            "signature": sym.get("signature") or "",
            "docstring": doc,
            "line_range": line_range,
            "badge": badge,
            "parent_symbol": sym.get("parent_symbol"),
        })

    classes = []
    class_map: Dict[str, Dict[str, Any]] = {}
    non_classes = []

    container_kinds = ("class", "struct", "interface", "trait", "enum", "extension", "mixin")
    for s in processed_symbols:
        if s["kind"].lower() in container_kinds:
            cl_data = {
                **s,
                "short_name": s["name"],
                "methods": [],
                "fields": [],
            }
            classes.append(cl_data)
            class_map[s["raw_id"]] = cl_data
        else:
            non_classes.append(s)

    top_level_funcs = []
    top_level_vars = []

    for s in non_classes:
        parent_class = None

        if s["parent_symbol"] and s["parent_symbol"] in class_map:
            parent_class = class_map[s["parent_symbol"]]

        if not parent_class:
            for cl in classes:
                if s["raw_id"].startswith(cl["raw_id"] + "::"):
                    parent_class = cl
                    break

        is_func = (
            s["kind"].lower() in ("method", "function", "constructor", "getter", "setter", "staticmethod")
            or s["signature"].strip().startswith(("def ", "@"))
        )

        s["short_name"] = s["name"]
        if parent_class:
            if is_func:
                parent_class["methods"].append(s)
            else:
                parent_class["fields"].append(s)
        else:
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
            header_title = f"{kind_label} {cl['short_name']}"
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
    exact_symbol: Dict[str, Any],
    occurrences: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    symbol_filepath_map: Optional[Dict[str, str]] = None,
) -> str:
    """Format lookup results for a canonical code symbol as markdown with unified references and call graph."""
    raw_symbol = str(exact_symbol.get("symbol", ""))
    disp_symbol = canonical_display_name(raw_symbol, exact_symbol.get("name"))
    filepath = exact_symbol.get("filepath")
    kind = exact_symbol.get("kind", "")
    signature = exact_symbol.get("signature")
    classification = exact_symbol.get("classification")
    parent_symbol = exact_symbol.get("parent_symbol")
    change_count = exact_symbol.get("change_count")
    docstring = exact_symbol.get("docstring")

    badge = format_classification_badge(classification) if classification else ""
    badge_header = f" `{badge}`" if badge else ""

    md = [
        f"## Code Symbol: `{disp_symbol}`{badge_header}\n",
        f"- **Filepath**: `{filepath or 'External / Third-party'}`",
        f"- **Kind**: `{kind}`",
        f"- **Signature**: `{signature or 'None'}`",
    ]
    if badge:
        md.append(f"- **Classification**: `{badge}`")
    if parent_symbol:
        md.append(f"- **Enclosing Symbol**: `{canonical_display_name(parent_symbol)}`")
    if change_count is not None:
        churn_str = f"High Churn ({change_count} modifications)" if change_count >= 3 else f"Stable ({change_count} edits)"
        md.append(f"- **Stability**: {churn_str}")
    doc = sanitize_docstring(docstring).strip() if docstring else "No docstring available."
    md.append(f"- **Docstring**:\n  {doc.replace(chr(10), chr(10) + '  ')}\n")

    file_occs: Dict[str, Dict[str, Any]] = {}
    norm_def_fp = str(filepath).replace("\\", "/") if filepath else None
    has_def_in_occs = any(
        str(o.get("filepath", "")).replace("\\", "/") == norm_def_fp and (o.get("role", 0) & 1)
        for o in (occurrences or [])
    )
    if norm_def_fp and not has_def_in_occs and exact_symbol.get("start_line") is not None:
        s_line = exact_symbol["start_line"]
        e_line = exact_symbol.get("end_line") or s_line
        file_occs[norm_def_fp] = {"lines": [(s_line, e_line)], "roles": {"Definition"}, "has_def": True}

    for o in occurrences or []:
        norm_fp = str(o["filepath"]).replace("\\", "/")
        s_line, e_line, role = o["start_line"], o["end_line"], o["role"]
        entry = file_occs.setdefault(norm_fp, {"lines": [], "roles": set(), "has_def": False})
        entry["lines"].append((s_line, e_line))
        if role & 1:
            entry["has_def"] = True
            entry["roles"].add("Definition")
        else:
            entry["roles"].add("Reference")
        if role & 4:
            entry["roles"].add("[Mutates]")
        if role & 8:
            entry["roles"].add("[Reads]")
        if role & 0x20:
            entry["roles"].add("[Test]")

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
        tags = [t for t in ("[Mutates]", "[Reads]", "[Test]") if t in role_set]
        if "Definition" in role_set:
            tags.append("[Def]")
        tag_str = " ".join(tags)
        if is_ref:
            return f"Reference {tag_str}".strip()
        return tag_str or "Reference"

    clean_edges = [
        e for e in (edges or [])
        if not str(e["source"]).startswith("local ") and not str(e["target"]).startswith("local ")
    ]
    sym_edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in clean_edges:
        src_raw, tgt_raw, rel = str(e["source"]), str(e["target"]), str(e["relation"])
        if tgt_raw == raw_symbol:
            direction, rel_raw = "←", src_raw
        elif src_raw == raw_symbol:
            direction, rel_raw = "→", tgt_raw
        else:
            direction, rel_raw = "←", src_raw

        rel_disp = canonical_display_name(rel_raw)
        key = (rel_raw, direction)
        if key not in sym_edges:
            fp = symbol_filepath_map.get(rel_raw) if symbol_filepath_map else None
            if not fp:
                parsed_fp, _, _ = parse_canonical_id(rel_raw)
                if parsed_fp and not parsed_fp.startswith("ext::"):
                    fp = parsed_fp
            sym_edges[key] = {
                "raw": rel_raw,
                "display": rel_disp,
                "direction": direction,
                "relations": set(),
                "fp": fp.replace("\\", "/") if fp else None,
            }
        sym_edges[key]["relations"].add(rel)

    matched_files = set()
    table_rows = []

    for fp, occ_data in file_occs.items():
        if occ_data["has_def"]:
            matched_files.add(fp)
            table_rows.append({
                "loc": f"`{fp}:{_format_lines(occ_data['lines'])}`",
                "sym": f"`{disp_symbol}`",
                "rel": "—",
                "role": "Definition",
                "order": (0, fp, disp_symbol),
            })

    for (_, _), data in sym_edges.items():
        fp = data["fp"]
        rel_str = f"{data['direction']} {', '.join(sorted(data['relations']))}"
        sym_label = f"`{data['display']}`"

        if fp and fp in file_occs:
            matched_files.add(fp)
            table_rows.append({
                "loc": f"`{fp}:{_format_lines(file_occs[fp]['lines'])}`",
                "sym": sym_label,
                "rel": rel_str,
                "role": _format_roles(file_occs[fp]["roles"]),
                "order": (1, fp, data["display"]),
            })
        else:
            table_rows.append({
                "loc": f"`{fp}`" if fp else "—",
                "sym": sym_label,
                "rel": rel_str,
                "role": "—",
                "order": (2, fp or "zzz", data["display"]),
            })

    for fp, occ_data in file_occs.items():
        if fp in matched_files:
            continue
        table_rows.append({
            "loc": f"`{fp}:{_format_lines(occ_data['lines'])}`",
            "sym": "—",
            "rel": "—",
            "role": _format_roles(occ_data["roles"]),
            "order": (3, fp, ""),
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
    exact_file: Dict[str, Any],
    file_symbols: List[Dict[str, Any]],
) -> str:
    """Format lookup results for a file module as markdown."""
    fp = exact_file.get("filepath", "")
    status = (exact_file.get("status") or "").replace("VIOLATION_DETECTED", "VIOLATION")
    justification = exact_file.get("justification") or "None"
    mf = exact_file.get("manual_fields")
    manual_str = json.dumps(mf) if isinstance(mf, dict) and mf else (str(mf) if mf and str(mf) != "{}" else "")

    md = [
        f"## File Module: `{fp}`\n",
        f"- **Status**: `{status}`",
        f"- **Justification**: *{justification}*",
    ]
    if manual_str:
        md.append(f"- **Manual Fields**: `{manual_str}`")
    md.append("")

    non_local_symbols = [s for s in file_symbols if not str(s["symbol"]).startswith("local ")]
    if non_local_symbols:
        md.append("### Symbols Declared in File")
        md.append("| Symbol | Kind |")
        md.append("| :--- | :--- |")
        for s in non_local_symbols:
            raw_s = s["symbol"]
            disp_s = canonical_display_name(raw_s, s.get("name"))
            kind = s.get("kind") or "Symbol"
            md.append(f"| `{disp_s}` | {kind} |")
        md.append("")

    return "\n".join(md)
