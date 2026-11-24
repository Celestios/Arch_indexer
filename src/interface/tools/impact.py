from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.helpers import detect_entry_point, is_test_caller
from utils.symbol_id import canonical_display_name, parse_canonical_id

_CONTAINER_KINDS = ("Class", "Struct", "Interface", "Trait", "Enum", "Extension", "Mixin")


def is_noisy_symbol(sym: str) -> bool:
    """Filter out local variables and standard library primitives/typing symbols."""
    s = str(sym)
    if s.startswith("local "):
        return True
    if s.startswith("ext::"):
        pkg_prefix, scope_parts, _ = parse_canonical_id(s)
        pkg_lower = (pkg_prefix or "").lower()
        if "python-stdlib" in pkg_lower or "/builtins" in pkg_lower or "/typing" in pkg_lower:
            return True
        if scope_parts and scope_parts[0] in ("builtins", "typing"):
            return True
    return False


def is_class_symbol(repository, db_symbol: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Check if the given symbol represents a container type in the repository."""
    sym_record = repository.graph.get_symbol(db_symbol)
    if sym_record and sym_record.get("kind") in _CONTAINER_KINDS:
        return True, sym_record
    if repository.graph.get_member_symbols(db_symbol):
        return True, sym_record
    return False, sym_record


def handle_impact(
    symbol: str,
    max_depth: int,
    repository,
    direction: str = "upstream",
    max_nodes: int = 50,
    project_root: Optional[Union[str, Path]] = None,
) -> str:
    """
    Blast radius analysis for a canonical symbol or container type.
    Enriches focal file with live Git hotspot risk and Lift-ranked temporal co-change coupling.
    """
    dir_norm = (direction or "upstream").lower()
    resolved = repository.graph.resolve_symbol(symbol)
    db_symbol = resolved["symbol"] if resolved else symbol
    clean_focal = canonical_display_name(db_symbol, resolved.get("name") if resolved else None)

    is_cls, sym_record = is_class_symbol(repository, db_symbol)
    if is_cls:
        res_md = _handle_class_impact(repository, db_symbol, clean_focal, direction=dir_norm)
    else:
        res_md = _handle_symbol_impact(
            repository,
            db_symbol,
            clean_focal,
            max_depth=max_depth,
            direction=dir_norm,
            max_nodes=max_nodes,
            sym_record=sym_record,
        )

    focal_fp = sym_record.get("filepath") if sym_record else None
    if focal_fp and project_root:
        from engines.git_analyzer import get_file_impact_telemetry
        telemetry = get_file_impact_telemetry(
            repository,
            Path(project_root),
            focal_fp,
            commits=100,
            coupling_limit=5,
        )
        hotspot = telemetry.get("hotspot")
        co_changes = telemetry.get("co_changes") or []
        if hotspot or co_changes:
            git_md = ["### Git Hotspot & Temporal Coupling"]
            if hotspot:
                git_md.append(
                    f"> **File Hotspot Risk**: `{hotspot['risk_tier']}` "
                    f"(risk={hotspot['risk_score']} | {hotspot['touches']} touches, "
                    f"{hotspot['bursts']} bursts, {hotspot['rework_pct']}% rework, "
                    f"fan-in={hotspot['fan_in']}, cx={hotspot['max_complexity']})"
                )
            if co_changes:
                git_md.append(f"> Modifying `{focal_fp}` historically co-changes with:")
                for c in co_changes:
                    git_md.append(
                        f"- [{c['coupling_type']}] `{c['filepath']}` "
                        f"({c['co_commits']} co-commits, conf={c['confidence_pct']}%, lift={c['lift']}x)"
                    )
            res_md += "\n" + "\n".join(git_md) + "\n"

    return res_md


def _render_call_tree(
    focal_symbol: str,
    items: List[Dict[str, Any]],
    entry_tags: Dict[str, str],
    max_nodes: int,
) -> List[str]:
    """Renders BFS closure items as a compact indented call tree rooted implicitly at focal_symbol."""
    children_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    included_syms = {item["symbol"] for item in items}

    for item in items:
        parent = item.get("parent")
        if not parent or (parent != focal_symbol and parent not in included_syms):
            parent = focal_symbol
        children_map[parent].append(item)

    for parent in children_map:
        children_map[parent].sort(key=lambda x: canonical_display_name(x["symbol"]))

    lines: List[str] = []
    emitted = 0
    total = len(items)

    def dfs(parent_sym: str, indent: int):
        nonlocal emitted
        for item in children_map.get(parent_sym, []):
            if emitted >= max_nodes:
                return
            emitted += 1
            sym = item["symbol"]
            clean_sym = canonical_display_name(sym)
            rel = item.get("relation")
            rel_tag = f" [{rel}]" if rel and rel != "Calls" else ""
            root_tag = f" [Root: {entry_tags[sym]}]" if sym in entry_tags else ""
            lines.append(f"{'  ' * indent}- `{clean_sym}`{rel_tag}{root_tag}")
            dfs(sym, indent + 1)

    dfs(focal_symbol, 0)
    omitted = total - emitted
    if omitted > 0:
        lines.append(f"- *... {omitted} more node(s) omitted (limit: {max_nodes}).*")
    return lines


def _handle_class_impact(
    repository,
    db_symbol: str,
    clean_focal: str,
    direction: str = "upstream",
) -> str:
    prefix = db_symbol + "::"
    method_rows = repository.graph.get_member_symbols(db_symbol)
    methods_list = [r["symbol"] for r in method_rows if r.get("symbol")]
    method_leaf_map = {
        r["symbol"]: (r.get("name") or parse_canonical_id(r["symbol"])[2])
        for r in method_rows
        if r.get("symbol")
    }
    member_set = set(methods_list) | {db_symbol}
    constructor_syms = {
        r["symbol"]
        for r in method_rows
        if r.get("symbol")
        and (r.get("kind") == "Constructor" or method_leaf_map[r["symbol"]] in ("__init__", "new"))
    }
    public_methods = [
        method_leaf_map[m]
        for m in methods_list
        if not method_leaf_map[m].startswith("_")
    ]

    md = [f"## Blast Radius for Class: `{clean_focal}` (direction: `{direction}`)\n"]
    if methods_list:
        if public_methods:
            md.append("**Public Interface**: " + ", ".join(f"`{m}`" for m in public_methods) + "\n")
    else:
        md.append(f"*No member methods registered for class `{clean_focal}`.*\n")

    if direction in ("upstream", "both"):
        direct_targets = [db_symbol] + sorted(constructor_syms)
        direct_edges = repository.graph.get_edges(targets=direct_targets)
        direct_usages = []
        seen_sources = set()
        for edge in direct_edges:
            src, tgt, rel = edge["source"], edge["target"], edge.get("relation")
            if is_noisy_symbol(src) or src in member_set or src.startswith(prefix) or src in seen_sources:
                continue
            seen_sources.add(src)
            if tgt in constructor_syms:
                role_tag = "Instantiation"
            elif rel in ("Inherits", "Extends"):
                role_tag = "Inheritance"
            elif rel == "TypeDefinition":
                role_tag = "Type Reference"
            else:
                role_tag = "Reference"
            direct_usages.append((canonical_display_name(src), role_tag))

        md.append("### Direct Usages")
        if not direct_usages:
            md.append("*No direct instantiations or type references found.*")
        else:
            for clean_src, role_tag in sorted(direct_usages):
                md.append(f"- `{clean_src}` [{role_tag}]")
        md.append("")

        md.append("### Interface Surface (Exposed Callers)")
        method_caller_map: Dict[str, List[str]] = defaultdict(list)
        all_caller_syms = set(seen_sources)
        if methods_list:
            for edge in repository.graph.get_edges(targets=methods_list):
                src, tgt = edge["source"], edge["target"]
                if is_noisy_symbol(src) or src in member_set or src.startswith(prefix):
                    continue
                all_caller_syms.add(src)
                short_m = method_leaf_map.get(tgt, parse_canonical_id(tgt)[2])
                clean_caller = canonical_display_name(src)
                if clean_caller not in method_caller_map[short_m]:
                    method_caller_map[short_m].append(clean_caller)

        if not method_caller_map:
            md.append("*No external callers recorded for member methods.*")
        else:
            for m_name, callers in sorted(method_caller_map.items()):
                md.append(f"- `{m_name}`: " + ", ".join(f"`{c}`" for c in sorted(callers)))
        md.append("")

        if all_caller_syms:
            meta_callers = repository.graph.get_symbols_by_ids(list(all_caller_syms))
            class_tests = []
            for c_sym in all_caller_syms:
                fp = meta_callers.get(c_sym, {}).get("filepath")
                if is_test_caller(c_sym, fp):
                    class_tests.append((canonical_display_name(c_sym), fp))
            if class_tests:
                md.append("### Covered By Tests")
                for ts, tfp in sorted(class_tests):
                    loc_str = f" in `{tfp}`" if tfp else ""
                    md.append(f"- `{ts}`{loc_str}")
                md.append("")

    if direction in ("downstream", "both"):
        md.append("### Downstream Dependencies (Per Method)")
        internal_by_method: Dict[str, List[str]] = defaultdict(list)
        external_by_method: Dict[str, List[str]] = defaultdict(list)

        if methods_list:
            for edge in repository.graph.get_edges(sources=methods_list):
                src, tgt = edge["source"], edge["target"]
                if is_noisy_symbol(tgt):
                    continue
                short_m = method_leaf_map.get(src, parse_canonical_id(src)[2])
                if tgt in member_set or tgt.startswith(prefix):
                    tgt_short = method_leaf_map.get(tgt, parse_canonical_id(tgt)[2])
                    if tgt_short not in internal_by_method[short_m]:
                        internal_by_method[short_m].append(tgt_short)
                else:
                    clean_tgt = canonical_display_name(tgt)
                    if clean_tgt not in external_by_method[short_m]:
                        external_by_method[short_m].append(clean_tgt)

        deps_found = False
        for m_sym in methods_list:
            short_m = method_leaf_map[m_sym]
            internal_calls = internal_by_method.get(short_m, [])
            external_calls = external_by_method.get(short_m, [])
            if internal_calls or external_calls:
                deps_found = True
                parts = []
                if internal_calls:
                    parts.append("Internal: " + ", ".join(f"`{c}`" for c in sorted(internal_calls)))
                if external_calls:
                    parts.append("External: " + ", ".join(f"`{c}`" for c in sorted(external_calls)))
                md.append(f"- `{short_m}` -> " + " | ".join(parts))

        if not deps_found:
            md.append("*No downstream dependencies recorded.*")
        md.append("")

    return "\n".join(md)


def _handle_symbol_impact(
    repository,
    db_symbol: str,
    clean_focal: str,
    max_depth: int = 4,
    direction: str = "upstream",
    max_nodes: int = 50,
    sym_record: Optional[Dict[str, Any]] = None,
) -> str:
    closure = repository.analytics.get_transitive_closure(db_symbol, max_depth=max_depth, direction=direction)

    md = [f"## Blast Radius for: `{clean_focal}` (direction: `{direction}`, max_depth: {max_depth})\n"]

    if sym_record is None:
        sym_record = repository.graph.get_symbol(db_symbol)
    change_count = sym_record.get("change_count", 1) if sym_record else 1
    if change_count >= 3:
        md.append(f"> **Symbol Churn**: High-Churn Hotspot ({change_count} indexed edits)\n")
    else:
        md.append(f"> **Symbol Churn**: Stable ({change_count} indexed edits)\n")

    if direction in ("upstream", "both"):
        raw_upstream = [item for item in closure.get("upstream", []) if not is_noisy_symbol(item.get("symbol", ""))]
        caller_syms = [item["symbol"] for item in raw_upstream]
        meta_batch = repository.graph.get_symbols_by_ids(caller_syms) if caller_syms else {}

        prod_upstream = []
        test_callers = []
        for item in raw_upstream:
            sym = item["symbol"]
            fp = meta_batch.get(sym, {}).get("filepath")
            if is_test_caller(sym, fp):
                test_callers.append((item, fp))
            else:
                prod_upstream.append(item)

        prod_syms = [item["symbol"] for item in prod_upstream]
        inc_counts: Counter = Counter()
        if prod_syms:
            for e in repository.graph.get_edges(targets=prod_syms):
                inc_counts[e["target"]] += 1

        entry_tags: Dict[str, str] = {}
        for item in prod_upstream:
            sym = item["symbol"]
            fp = meta_batch.get(sym, {}).get("filepath")
            ep = detect_entry_point(sym, fp, inc_counts.get(sym, 0))
            if ep:
                entry_tags[sym] = ep

        md.append("### Upstream Callers")
        if not prod_upstream:
            md.append("*No transitive upstream callers found.*")
        else:
            md.extend(_render_call_tree(db_symbol, prod_upstream, entry_tags, max_nodes=max_nodes))
        md.append("")

        if test_callers:
            md.append("### Covered By Tests")
            seen_tests = set()
            for item, fp in sorted(test_callers, key=lambda x: (x[0]["depth"], canonical_display_name(x[0]["symbol"]))):
                clean_test = canonical_display_name(item["symbol"])
                if clean_test in seen_tests:
                    continue
                seen_tests.add(clean_test)
                loc_str = f" in `{fp}`" if fp else ""
                md.append(f"- `{clean_test}`{loc_str} [Depth: {item['depth']}]")
            md.append("")

    if direction in ("downstream", "both"):
        downstream = [item for item in closure.get("downstream", []) if not is_noisy_symbol(item.get("symbol", ""))]
        md.append("### Downstream Callees")
        if not downstream:
            md.append("*No transitive downstream callees found.*")
        else:
            md.extend(_render_call_tree(db_symbol, downstream, {}, max_nodes=max_nodes))
        md.append("")

    return "\n".join(md)
