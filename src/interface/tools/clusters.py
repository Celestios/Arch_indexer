"""MCP tool and CLI shared handler for parameter-free hierarchical clustering."""
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from clustering.models import ClusterNode, ClusterHierarchyResult
from clustering.analyzer import build_cluster_hierarchy
from interface.validators import validate_cluster_view, validate_cluster_unit
from utils.helpers import demangle_scip_symbol, resolve_symbol_in_repo


def _collect_frontier(node: ClusterNode, max_depth: int, current_depth: int = 0) -> List[ClusterNode]:
    """Collects visible frontier clusters at current depth or leaves."""
    if current_depth >= max_depth or not node.children:
        return [node] if node.cluster_id != "root" else node.children
    res: List[ClusterNode] = []
    for c in node.children:
        res.extend(_collect_frontier(c, max_depth, current_depth + 1))
    return res


def _format_node_line(node: ClusterNode, unit: str, indent: str = "") -> str:
    """Formats a single cluster tree node line matching specification."""
    s_cnt = len(node.symbol_ids)
    f_cnt = len(node.filepaths)

    if node.is_singleton:
        fp_str = f" | {node.filepaths[0]}" if node.filepaths else ""
        return f"{indent}[{node.cluster_id}] {node.name} ({s_cnt}s | {f_cnt}f{fp_str}) [in: {node.ext_caller_count}, out: {node.ext_dep_count}]"

    cycle_str = " [cycle]" if node.is_cycle else ""
    closure_str = f" | closure: {node.closure_ext_count}" if node.closure_ext_count > 0 else ""
    return (
        f"{indent}[{node.cluster_id}] {node.name} "
        f"({f_cnt}f, {s_cnt:,}s | containment: {round(node.containment_pct)}% | ext: {node.ext_dep_count}{closure_str}){cycle_str}"
    )


def _render_tree(
    node: ClusterNode,
    unit: str,
    max_depth: int,
    current_depth: int = 0,
    indent: str = " ",
) -> List[str]:
    """Renders indented cluster tree up to max_depth."""
    lines: List[str] = []
    if current_depth > 0:
        lines.append(_format_node_line(node, unit, indent))
        for note in node.drift_notes:
            lines.append(f"{indent}  ! {note}")

    if current_depth < max_depth and node.children:
        next_indent = indent + "    " if current_depth > 0 else " "
        for c in node.children:
            lines.extend(_render_tree(c, unit, max_depth, current_depth + 1, next_indent))
    return lines


def _render_mermaid(
    frontier_nodes: List[ClusterNode],
    unit: str,
    result: ClusterHierarchyResult,
) -> List[str]:
    """Renders Mermaid diagram strictly between visible frontier nodes, mapping leaf dependencies up to visible frontier."""
    lines = ["Dependency Frontier (Mermaid)", "```mermaid", "graph LR"]
    if not frontier_nodes:
        lines.append("```")
        return lines

    # Capped at 35 if needed
    note_line = None
    if len(frontier_nodes) > 35:
        frontier_nodes.sort(key=lambda n: n.ext_dep_count + n.ext_caller_count, reverse=True)
        frontier_nodes = frontier_nodes[:35]
        note_line = "> *Note: Frontier diagram capped to top 35 clusters by connectivity. Use `depth=1` or pass `--cluster <ID>` to zoom.*"

    # Map each symbol to its owning visible frontier cluster ID
    sym_to_frontier: Dict[str, str] = {}
    node_by_frontier_id: Dict[str, ClusterNode] = {}
    for fn in frontier_nodes:
        node_by_frontier_id[fn.cluster_id] = fn
        for s in fn.symbol_ids:
            sym_to_frontier[s] = fn.cluster_id

    # Compute inter-frontier directed weights
    frontier_edges: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for fn in frontier_nodes:
        src_cid = fn.cluster_id
        for target_list in fn.ext_deps_by_cluster.values():
            for t in target_list:
                tgt_frontier_cid = sym_to_frontier.get(t)
                if tgt_frontier_cid and tgt_frontier_cid != src_cid:
                    frontier_edges[(src_cid, tgt_frontier_cid)].add(t)

    rendered_nodes: Set[str] = set()
    edge_lines: List[str] = []

    for (src_cid, tgt_cid), tgts in sorted(frontier_edges.items()):
        src_node = node_by_frontier_id[src_cid]
        tgt_node = node_by_frontier_id[tgt_cid]

        src_san = src_cid.replace(".", "_")
        tgt_san = tgt_cid.replace(".", "_")

        src_name = src_node.name.replace('"', "'")
        tgt_name = tgt_node.name.replace('"', "'")

        src_lbl = f'{src_cid} {src_name} ({len(src_node.symbol_ids)}s)' if unit == "symbol" else f'{src_cid} {src_name} ({len(src_node.filepaths)}f)'
        tgt_lbl = f'{tgt_cid} {tgt_name} ({len(tgt_node.symbol_ids)}s)' if unit == "symbol" else f'{tgt_cid} {tgt_name} ({len(tgt_node.filepaths)}f)'

        src_def = f'{src_san}["{src_lbl}"]' if src_san not in rendered_nodes else src_san
        tgt_def = f'{tgt_san}["{tgt_lbl}"]' if tgt_san not in rendered_nodes else tgt_san
        rendered_nodes.add(src_san)
        rendered_nodes.add(tgt_san)

        weight = len(tgts)
        edge_lines.append(f"  {src_def} -->|{weight}| {tgt_def}")

    # Include isolated frontier nodes without incident edges
    for fn in frontier_nodes:
        san = fn.cluster_id.replace(".", "_")
        if san not in rendered_nodes:
            fn_name = fn.name.replace('"', "'")
            lbl = f'{fn.cluster_id} {fn_name} ({len(fn.symbol_ids)}s)' if unit == "symbol" else f'{fn.cluster_id} {fn_name} ({len(fn.filepaths)}f)'
            edge_lines.append(f'  {san}["{lbl}"]')

    lines.extend(edge_lines)
    lines.append("```")
    if note_line:
        lines.append(note_line)
    return lines


def _render_drift(drift: Any) -> List[str]:
    """Renders architectural drift summary."""
    lines = ["Architectural Drift Summary"]
    has_drift = False

    if drift.split_files:
        has_drift = True
        lines.append(f" * Split-Brain Files ({len(drift.split_files)}):")
        for sf in drift.split_files[:10]:
            dist_str = ", ".join(f"{cnt} in {c}" for c, cnt in sf.get("distribution", {}).items())
            lines.append(f"   * {sf['filepath']} (purity: {round(sf['purity_pct'])}% - {dist_str})")
        if len(drift.split_files) > 10:
            lines.append(f"   * ... and {len(drift.split_files) - 10} more files")

    if drift.split_classes:
        has_drift = True
        lines.append(f" * Split-Brain Classes ({len(drift.split_classes)}):")
        for sc in drift.split_classes[:10]:
            clean = demangle_scip_symbol(sc['class_symbol'])
            fp_str = f" in {sc['filepath']}" if sc.get('filepath') else ""
            dist_str = ", ".join(f"{cnt} in {c}" for c, cnt in sc.get("distribution", {}).items())
            lines.append(f"   * {clean}{fp_str} (purity: {round(sc['purity_pct'])}% - {dist_str})")
        if len(drift.split_classes) > 10:
            lines.append(f"   * ... and {len(drift.split_classes) - 10} more classes")

    if drift.misplaced_symbols:
        has_drift = True
        lines.append(f" * Misplaced Symbols ({len(drift.misplaced_symbols)}):")
        for ms in drift.misplaced_symbols[:10]:
            clean = ms.get('clean_symbol') or demangle_scip_symbol(ms['symbol'])
            lines.append(f"   * `{clean}` (in `{ms['filepath']}`): belongs to `{ms['assigned_cluster']}`, file is in `{ms['file_cluster']}`")
        if len(drift.misplaced_symbols) > 10:
            lines.append(f"   * ... and {len(drift.misplaced_symbols) - 10} more symbols")

    if not has_drift:
        lines.append(" * No architectural drift detected across files, classes, or modules.")
    return lines


def _render_leaf_inspection(
    node: ClusterNode,
    result: ClusterHierarchyResult,
    repository,
) -> List[str]:
    """Renders Mode B: Leaf / Zoom Inspection with actionable audit targets."""
    lines: List[str] = [
        f"### Cluster Details: `[{node.cluster_id}] {node.name}`",
        f"- **Level**: {node.level} | **Cycle**: {node.is_cycle} | **Containment**: {node.containment_pct}%",
        f"- **Files**: {len(node.filepaths)} | **Symbols**: {len(node.symbol_ids)}",
        f"- **External Targets**: {node.ext_dep_count} | **External Callers**: {node.ext_caller_count}",
        "",
        "#### Member Files & Symbols",
    ]

    # One single batch query for all member symbols to prevent N+1 DuckDB queries
    sym_info_map = (
        repository.graph.get_symbols_by_ids(list(node.symbol_ids))
        if hasattr(repository, "graph")
        else {}
    )

    symbols_by_file: Dict[str, List[str]] = defaultdict(list)
    for s in sorted(node.symbol_ids):
        sym_info = sym_info_map.get(s)
        fp = sym_info.get("filepath") if sym_info else (node.filepaths[0] if len(node.filepaths) == 1 else "unknown")
        clean = (sym_info.get("clean_symbol") if sym_info else None) or demangle_scip_symbol(s)
        line_info = f" (L{sym_info['start_line']})" if sym_info and sym_info.get("start_line") is not None else ""
        symbols_by_file[fp or "unknown"].append(f"`{clean}`{line_info}")

    for fp, sym_list in sorted(symbols_by_file.items()):
        lines.append(f"- **`{fp}`** ({len(sym_list)} symbols):")
        for s_desc in sym_list[:25]:
            lines.append(f"  - {s_desc}")
        if len(sym_list) > 25:
            lines.append(f"  - ... and {len(sym_list) - 25} more symbols")

    lines.append("")
    lines.append("#### External Boundary Dependencies (Grouped by Owning Cluster)")
    if not node.ext_deps_by_cluster:
        lines.append("*No external dependencies.*")
    else:
        for c_id, targets in sorted(node.ext_deps_by_cluster.items()):
            c_node = result.index_by_id.get(c_id)
            c_name = f" {c_node.name}" if c_node else ""
            lines.append(f"- **`[{c_id}]{c_name}`** ({len(targets)} targets):")
            for t in targets[:15]:
                clean_t = demangle_scip_symbol(t)
                lines.append(f"  -> `{clean_t}`")
            if len(targets) > 15:
                lines.append(f"  -> ... and {len(targets) - 15} more targets")

    lines.append("")
    return lines


def handle_clusters(
    repository,
    project_root: Path,
    cluster: Optional[str] = None,
    depth: int = 2,
    unit: str = "symbol",
    view: str = "both",
    scope: Optional[Union[str, List[str]]] = None,
    language: Optional[str] = None,
    include_tests: bool = False,
    include_drift: bool = True,
) -> str:
    """Handles cluster hierarchy navigation, depth slicing, and view formatting."""
    ok_v, view_or_err = validate_cluster_view(view)
    if not ok_v:
        return f"Error: {view_or_err}"
    view_mode = view_or_err

    ok_u, unit_or_err = validate_cluster_unit(unit)
    if not ok_u:
        return f"Error: {unit_or_err}"
    unit_mode = unit_or_err

    depth_val = max(1, int(depth))

    root_path = Path(project_root).resolve()
    result = build_cluster_hierarchy(
        repository=repository,
        project_root=root_path,
        scope=scope,
        language=language,
        include_tests=include_tests,
        unit=unit_mode,
    )

    # Handle special unreferenced inspection
    if cluster and cluster.strip().lower() in ("unreferenced", "unref"):
        unref = result.unreferenced_symbols
        lines = [
            f"## Unreferenced Symbols ({len(unref)} symbols)",
            f"- **Focus**: `unreferenced` (isolated symbols with zero dependency edges)",
            "",
        ]
        if not unref:
            lines.append("*No unreferenced symbols in active scope.*")
        else:
            by_file = defaultdict(list)
            for u in unref:
                by_file[u.get("filepath") or "unknown"].append(u)
            for fp, items in sorted(by_file.items()):
                lines.append(f"### `{fp}` ({len(items)} symbols)")
                for item in items[:30]:
                    lines.append(f"- `{item['clean_symbol']}` ({item.get('kind', 'Symbol')})")
                if len(items) > 30:
                    lines.append(f"- ... and {len(items) - 30} more symbols")
                lines.append("")
        return "\n".join(lines).rstrip()

    # Resolve target cluster node
    target_node: Optional[ClusterNode] = None
    target_clean = cluster.strip() if cluster else None

    if not target_clean or target_clean.lower() in ("root", "all", "."):
        target_node = result.root
    elif target_clean in result.index_by_id:
        target_node = result.index_by_id[target_clean]
    else:
        # 1. Check if target is an exact symbol
        matched_cid = result.symbol_to_leaf.get(target_clean)

        # 2. Check symbol in repo
        if not matched_cid and hasattr(repository, "graph"):
            resolved_sym = resolve_symbol_in_repo(repository, target_clean)
            if resolved_sym:
                matched_cid = result.symbol_to_leaf.get(resolved_sym.get("symbol", ""))

        # 3. Check by clean symbol suffix
        if not matched_cid:
            for s, cid in result.symbol_to_leaf.items():
                if s == target_clean or s.endswith(f".{target_clean}") or demangle_scip_symbol(s) == target_clean:
                    matched_cid = cid
                    break

        # 4. Check by filepath (POSIX normalized, skipping root to jump directly to finest enclosing cluster)
        if not matched_cid:
            norm_target = target_clean.replace("\\", "/").strip("/")
            matching_nodes: List[ClusterNode] = []
            for c_id, node in result.index_by_id.items():
                if c_id == "root":
                    continue
                for fp in node.filepaths:
                    norm_fp = fp.replace("\\", "/").strip("/")
                    if norm_fp == norm_target or norm_fp.endswith("/" + norm_target) or norm_fp.endswith(norm_target):
                        matching_nodes.append(node)
                        break

            if matching_nodes:
                # Pick finest/deepest cluster (smallest total_symbols, then largest level)
                matching_nodes.sort(key=lambda n: (len(n.symbol_ids), -n.level))
                matched_cid = matching_nodes[0].cluster_id

        if matched_cid and matched_cid in result.index_by_id:
            target_node = result.index_by_id[matched_cid]
        else:
            return f"Error: Cluster, symbol, or filepath '{cluster}' not found in cluster hierarchy."

    # Render header
    hdr_focus = target_node.cluster_id
    md: List[str] = [
        f"## Emergent Dependency Clusters ({result.total_files} files, {result.total_symbols:,} symbols, {result.total_edges:,} edges)",
        f"- **Focus**: `{hdr_focus}` (depth={depth_val}, unit=`{unit_mode}`)",
        f"- **Unreferenced Symbols**: {len(result.unreferenced_symbols)} (pass `cluster=\"unreferenced\"` to inspect)",
        "",
    ]

    is_leaf = not target_node.children or target_node.is_singleton

    # If zoomed into a leaf, provide Mode B Leaf Inspection
    if is_leaf and target_node.cluster_id != "root":
        md.extend(_render_leaf_inspection(target_node, result, repository))
    else:
        # Tree View
        if view_mode in ("tree", "both"):
            md.append("### Cluster Tree")
            md.append("```text")
            tree_root_lbl = f"{target_node.cluster_id} ({len(target_node.filepaths)} files, {len(target_node.symbol_ids):,} symbols)"
            md.append(tree_root_lbl)
            tree_lines = _render_tree(target_node, unit=unit_mode, max_depth=depth_val, current_depth=0)
            md.extend(tree_lines)
            md.append("```")
            md.append("")

        # Mermaid View
        if view_mode in ("mermaid", "both"):
            frontier = _collect_frontier(target_node, max_depth=depth_val)
            md.extend(_render_mermaid(frontier, unit=unit_mode, result=result))
            md.append("")

    # Drift Summary
    if include_drift:
        md.extend(_render_drift(result.drift))
        md.append("")

    return "\n".join(md).rstrip()
