"""MCP tool and CLI shared handler for parameter-free hierarchical clustering."""
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from clustering.analyzer import build_cluster_hierarchy
from clustering.metrics import compute_quotient_cycles
from clustering.models import ClusterHierarchyResult, ClusterNode
from interface.validators import validate_cluster_unit, validate_cluster_view
from utils.symbol_id import canonical_display_name, parse_canonical_id


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
        macro_str = (
            f" [macro-cycle ↔️ {', '.join(node.macro_cycle_peers)} ({node.cyclic_ext_dep_count})]"
            if node.macro_cycle_peers
            else ""
        )
        return (
            f"{indent}[{node.cluster_id}] {node.name} ({s_cnt}s | {f_cnt}f{fp_str}) "
            f"[in: {node.ext_caller_count}, out: {node.ext_dep_count} | I: {node.instability:.2f}]{macro_str}"
        )

    cycle_str = " [local-cycle]" if node.is_cycle else ""
    macro_str = (
        f" [macro-cycle ↔️ {', '.join(node.macro_cycle_peers)} ({node.cyclic_ext_dep_count})]"
        if node.macro_cycle_peers
        else ""
    )
    closure_str = f" | closure: {node.closure_ext_count}" if node.closure_ext_count > 0 else ""
    return (
        f"{indent}[{node.cluster_id}] {node.name} "
        f"({f_cnt}f, {s_cnt:,}s | containment: {round(node.containment_pct)}% | ext: {node.ext_dep_count}{closure_str} | I: {node.instability:.2f}){cycle_str}{macro_str}"
    )


def _partition_root_nodes(root: ClusterNode) -> Tuple[List[ClusterNode], List[ClusterNode], List[ClusterNode]]:
    """
    Partitions root-level children topologically (zero numeric cutoffs):
    1. Composite clusters (multi-symbol subsystems)
    2. Shared hubs (singletons coupling to >= 2 sibling root clusters)
    3. Residuals (singletons coupling to <= 1 sibling root cluster)
    """
    composite: List[ClusterNode] = []
    hubs: List[ClusterNode] = []
    residuals: List[ClusterNode] = []

    root_cids = {c.cluster_id for c in root.children}
    coupled_siblings: Dict[str, Set[str]] = defaultdict(set)

    for c in root.children:
        c_id = c.cluster_id
        for tgt_cid in c.ext_deps_by_cluster.keys():
            if tgt_cid != "external":
                tgt_root = tgt_cid.split(".")[0]
                if tgt_root != c_id and tgt_root in root_cids:
                    coupled_siblings[c_id].add(tgt_root)
                    coupled_siblings[tgt_root].add(c_id)

    for c in root.children:
        if not c.is_singleton and len(c.symbol_ids) > 1:
            composite.append(c)
        else:
            sibling_count = len(coupled_siblings.get(c.cluster_id, set()))
            if sibling_count >= 2:
                hubs.append(c)
            else:
                residuals.append(c)

    hubs.sort(
        key=lambda c: (
            -len(coupled_siblings.get(c.cluster_id, set())),
            -(c.ext_caller_count + c.ext_dep_count),
            c.name,
        )
    )

    return composite, hubs, residuals


def _render_summary_table(
    nodes: List[ClusterNode],
    total_symbols: int,
    total_files: int,
    shared_hubs_count: int = 0,
    residuals_count: int = 0,
    macro_cycles_count: int = 0,
) -> List[str]:
    lines: List[str] = [
        "### Macro Subsystems Overview",
        "",
        "| Cluster | Files | Symbols | Containment | Ext (Closure) | Ext Callers | I | Macro Cycle | Dominant Path |",
        "|:---|---:|---:|---:|---:|---:|---:|:---|:---|",
    ]
    symbols_covered = 0
    for node in nodes:
        f_cnt = len(node.filepaths)
        s_cnt = len(node.symbol_ids)
        symbols_covered += s_cnt
        dom = node.dominant_dir or (node.filepaths[0] if node.filepaths else "-")
        c_pct = f"{round(node.containment_pct)}%" if not node.is_singleton else "-"
        ext_col = f"{node.ext_dep_count:,} ({node.closure_ext_count:,})"
        macro_col = (
            f"↔️ {', '.join(node.macro_cycle_peers)} ({node.cyclic_ext_dep_count})"
            if node.macro_cycle_peers
            else "—"
        )
        lines.append(
            f"| `{node.cluster_id}` {node.name} | {f_cnt:,} | {s_cnt:,} | {c_pct} | {ext_col} | {node.ext_caller_count:,} | {node.instability:.2f} | {macro_col} | `{dom}` |"
        )

    lines.append("")
    cov_pct = round((symbols_covered / max(1, total_symbols)) * 100.0, 1)
    macro_str = f"macro cycles: {macro_cycles_count} (DAG)" if macro_cycles_count == 0 else f"macro cycles: {macro_cycles_count}"
    telemetry = [
        f"**Coverage**: {len(nodes)} macro clusters covering {cov_pct}% of clustered symbols ({symbols_covered:,}/{total_symbols:,})",
        macro_str,
    ]
    if shared_hubs_count > 0:
        telemetry.append(f"{shared_hubs_count} shared hubs")
    if residuals_count > 0:
        telemetry.append(f"{residuals_count} collapsed residuals (pass `cluster=\"residuals\"` to inspect)")

    lines.append(" * " + " | ".join(telemetry))
    return lines


def _render_tree(
    node: ClusterNode,
    unit: str,
    max_depth: int,
    current_depth: int = 0,
    indent: str = " ",
    filter_residuals: bool = False,
) -> List[str]:
    lines: List[str] = []
    if current_depth > 0:
        lines.append(_format_node_line(node, unit, indent))
        for note in node.drift_notes:
            lines.append(f"{indent}  ! {note}")

    if current_depth < max_depth and node.children:
        next_indent = indent + "    " if current_depth > 0 else " "
        children_to_render = node.children
        residual_count = 0
        if current_depth == 0 and filter_residuals:
            composite, hubs, residuals = _partition_root_nodes(node)
            children_to_render = composite + hubs
            residual_count = len(residuals)

        for c in children_to_render:
            lines.extend(_render_tree(c, unit, max_depth, current_depth + 1, next_indent))

        if residual_count > 0:
            lines.append(f"{next_indent}[residuals] {residual_count} peripheral symbols (low coupling) - pass cluster=\"residuals\" to inspect")

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

    note_line = None
    if len(frontier_nodes) > 35:
        frontier_nodes.sort(key=lambda n: n.ext_dep_count + n.ext_caller_count, reverse=True)
        frontier_nodes = frontier_nodes[:35]
        note_line = "> *Note: Frontier diagram capped to top 35 clusters by connectivity. Use `depth=1` or pass `--cluster <ID>` to zoom.*"

    leaf_to_frontier: Dict[str, str] = {}
    node_by_frontier_id: Dict[str, ClusterNode] = {}

    def _map_descendants(node: ClusterNode, frontier_cid: str):
        leaf_to_frontier[node.cluster_id] = frontier_cid
        for child in node.children:
            _map_descendants(child, frontier_cid)

    for fn in frontier_nodes:
        node_by_frontier_id[fn.cluster_id] = fn
        _map_descendants(fn, fn.cluster_id)

    frontier_edges: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for fn in frontier_nodes:
        src_cid = fn.cluster_id
        for tgt_leaf_cid, target_list in fn.ext_deps_by_cluster.items():
            tgt_frontier_cid = leaf_to_frontier.get(tgt_leaf_cid)
            if tgt_frontier_cid and tgt_frontier_cid != src_cid:
                for t in target_list:
                    frontier_edges[(src_cid, tgt_frontier_cid)].add(t)

    cyclic_edges = compute_quotient_cycles(frontier_nodes)["cyclic_edges"]

    rendered_nodes: Set[str] = set()
    edge_lines: List[str] = []

    for (src_cid, tgt_cid), tgts in sorted(frontier_edges.items()):
        src_node = node_by_frontier_id[src_cid]
        tgt_node = node_by_frontier_id[tgt_cid]

        src_san = src_cid.replace(".", "_")
        tgt_san = tgt_cid.replace(".", "_")

        src_name = src_node.name.replace('"', "'")
        tgt_name = tgt_node.name.replace('"', "'")

        src_lbl = f"{src_cid} {src_name} ({len(src_node.symbol_ids)}s)" if unit == "symbol" else f"{src_cid} {src_name} ({len(src_node.filepaths)}f)"
        tgt_lbl = f"{tgt_cid} {tgt_name} ({len(tgt_node.symbol_ids)}s)" if unit == "symbol" else f"{tgt_cid} {tgt_name} ({len(tgt_node.filepaths)}f)"

        src_def = f'{src_san}["{src_lbl}"]' if src_san not in rendered_nodes else src_san
        tgt_def = f'{tgt_san}["{tgt_lbl}"]' if tgt_san not in rendered_nodes else tgt_san
        rendered_nodes.add(src_san)
        rendered_nodes.add(tgt_san)

        if (src_cid, tgt_cid) in cyclic_edges:
            edge_lines.append(f"  {src_def} ==>|{len(tgts)} cyclic| {tgt_def}")
        else:
            edge_lines.append(f"  {src_def} -->|{len(tgts)}| {tgt_def}")

    for fn in frontier_nodes:
        san = fn.cluster_id.replace(".", "_")
        if san not in rendered_nodes:
            fn_name = fn.name.replace('"', "'")
            lbl = f"{fn.cluster_id} {fn_name} ({len(fn.symbol_ids)}s)" if unit == "symbol" else f"{fn.cluster_id} {fn_name} ({len(fn.filepaths)}f)"
            edge_lines.append(f'  {san}["{lbl}"]')

    lines.extend(edge_lines)
    lines.append("```")
    if note_line:
        lines.append(note_line)
    return lines


def _render_drift(drift: Any) -> List[str]:
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
            disp = canonical_display_name(sc["class_symbol"])
            fp_str = f" in {sc['filepath']}" if sc.get("filepath") else ""
            dist_str = ", ".join(f"{cnt} in {c}" for c, cnt in sc.get("distribution", {}).items())
            lines.append(f"   * {disp}{fp_str} (purity: {round(sc['purity_pct'])}% - {dist_str})")
        if len(drift.split_classes) > 10:
            lines.append(f"   * ... and {len(drift.split_classes) - 10} more classes")

    if drift.misplaced_symbols:
        has_drift = True
        lines.append(f" * Misplaced Symbols ({len(drift.misplaced_symbols)}):")
        for ms in drift.misplaced_symbols[:10]:
            disp = ms.get("name") or canonical_display_name(ms["symbol"])
            lines.append(f"   * `{disp}` (in `{ms['filepath']}`): belongs to `{ms['assigned_cluster']}`, file is in `{ms['file_cluster']}`")
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
    peers_str = (
        f"{', '.join(node.macro_cycle_peers)} ({node.cyclic_ext_dep_count} cyclic targets)"
        if node.macro_cycle_peers
        else "None (acyclic)"
    )
    lines: List[str] = [
        f"### Cluster Details: `[{node.cluster_id}] {node.name}`",
        f"- **Level**: {node.level} | **Cycle**: {node.is_cycle} | **Containment**: {node.containment_pct}% | **Instability (I)**: {node.instability:.2f}",
        f"- **Files**: {len(node.filepaths)} | **Symbols**: {len(node.symbol_ids)}",
        f"- **External Targets**: {node.ext_dep_count} | **Closure**: {node.closure_ext_count} | **External Callers**: {node.ext_caller_count}",
        f"- **Macro Cycle Peers**: {peers_str}",
        "",
        "#### Member Files & Symbols",
    ]

    sym_info_map = (
        repository.graph.get_symbols_by_ids(list(node.symbol_ids))
        if hasattr(repository, "graph")
        else {}
    )

    symbols_by_file: Dict[str, List[str]] = defaultdict(list)
    for s in sorted(node.symbol_ids):
        sym_info = sym_info_map.get(s)
        fp = sym_info.get("filepath") if sym_info else (node.filepaths[0] if len(node.filepaths) == 1 else "unknown")
        disp = canonical_display_name(s, sym_info.get("name") if sym_info else None)
        line_info = f" (L{sym_info['start_line']})" if sym_info and sym_info.get("start_line") is not None else ""
        symbols_by_file[fp or "unknown"].append(f"`{disp}`{line_info}")

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
        cyclic_peers: Set[str] = set()
        curr: Optional[ClusterNode] = node
        while curr is not None:
            cyclic_peers.update(curr.macro_cycle_peers)
            curr = result.index_by_id.get(curr.parent_id) if curr.parent_id else None

        for c_id, targets in sorted(node.ext_deps_by_cluster.items()):
            c_node = result.index_by_id.get(c_id)
            c_name = f" {c_node.name}" if c_node else ""
            inst_str = f" (I={c_node.instability:.2f})" if c_node else ""
            is_cyclic_target = c_id in cyclic_peers
            if not is_cyclic_target and c_node is not None:
                anc = result.index_by_id.get(c_node.parent_id) if c_node.parent_id else None
                while anc is not None:
                    if anc.cluster_id in cyclic_peers:
                        is_cyclic_target = True
                        break
                    anc = result.index_by_id.get(anc.parent_id) if anc.parent_id else None
            cyclic_tag = " [CYCLIC]" if is_cyclic_target else ""
            lines.append(f"- **`[{c_id}]{c_name}`**{inst_str}{cyclic_tag} ({len(targets)} targets):")
            for t in targets[:15]:
                disp_t = canonical_display_name(t) if "::" in t else t
                lines.append(f"  -> `{disp_t}`")
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

    composite_roots, hub_roots, residual_roots = _partition_root_nodes(result.root)

    if cluster and cluster.strip().lower() == "residuals":
        lines = [
            f"## Low-Connectivity Residuals ({len(residual_roots)} singletons)",
            "- **Focus**: `residuals` (peripheral symbols with low external coupling)",
            "",
        ]
        if not residual_roots:
            lines.append("*No residual singletons at root.*")
        else:
            by_file = defaultdict(list)
            for r in residual_roots:
                fp = r.filepaths[0] if r.filepaths else "unknown"
                by_file[fp].append(r)
            for fp, items in sorted(by_file.items()):
                lines.append(f"### `{fp}` ({len(items)} symbols)")
                for item in items[:30]:
                    lines.append(f"- `[{item.cluster_id}]` {item.name} [in: {item.ext_caller_count}, out: {item.ext_dep_count}]")
                if len(items) > 30:
                    lines.append(f"- ... and {len(items) - 30} more symbols")
                lines.append("")
        return "\n".join(lines).rstrip()

    if cluster and cluster.strip().lower() == "unreferenced":
        unref = result.unreferenced_symbols
        lines = [
            f"## Unreferenced Symbols ({len(unref)} symbols)",
            "- **Focus**: `unreferenced` (isolated symbols with zero dependency edges)",
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
                    disp = canonical_display_name(item.get("symbol", ""), item.get("name"))
                    lines.append(f"- `{disp}` ({item.get('kind', 'Symbol')})")
                if len(items) > 30:
                    lines.append(f"- ... and {len(items) - 30} more symbols")
                lines.append("")
        return "\n".join(lines).rstrip()

    target_node: Optional[ClusterNode] = None
    target_clean = cluster.strip() if cluster else None

    if not target_clean or target_clean.lower() == "root":
        target_node = result.root
    elif target_clean in result.index_by_id:
        target_node = result.index_by_id[target_clean]
    else:
        matched_cid = result.symbol_to_leaf.get(target_clean)

        if not matched_cid and hasattr(repository, "graph"):
            resolved_sym = repository.graph.resolve_symbol(target_clean)
            if resolved_sym:
                matched_cid = result.symbol_to_leaf.get(resolved_sym.get("symbol", ""))

        if not matched_cid:
            for s, cid in result.symbol_to_leaf.items():
                if s == target_clean or canonical_display_name(s) == target_clean or parse_canonical_id(s)[2] == target_clean:
                    matched_cid = cid
                    break

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
                matching_nodes.sort(key=lambda n: (len(n.symbol_ids), -n.level))
                matched_cid = matching_nodes[0].cluster_id

        if matched_cid and matched_cid in result.index_by_id:
            target_node = result.index_by_id[matched_cid]
        else:
            return f"Error: Cluster, symbol, or filepath '{cluster}' not found in cluster hierarchy."

    hdr_focus = target_node.cluster_id
    macro_cycles_hdr = (
        "0 (DAG)"
        if target_node.internal_macro_cycles == 0
        else f"{target_node.internal_macro_cycles} sibling cycle(s)"
    )
    md: List[str] = [
        f"## Emergent Dependency Clusters ({result.total_files} files, {result.total_symbols:,} symbols, {result.total_edges:,} edges)",
        f"- **Focus**: `{hdr_focus}` (depth={depth_val}, unit=`{unit_mode}`)",
        f"- **Macro Cycles**: {macro_cycles_hdr}",
        f"- **Unreferenced Symbols**: {len(result.unreferenced_symbols)} (pass `cluster=\"unreferenced\"` to inspect)",
        f"- **Residual Singletons**: {len(residual_roots)} (pass `cluster=\"residuals\"` to inspect)",
        "",
    ]

    is_leaf = not target_node.children or target_node.is_singleton

    if is_leaf and target_node.cluster_id != "root":
        md.extend(_render_leaf_inspection(target_node, result, repository))
    else:
        if view_mode == "summary":
            summary_targets = composite_roots + hub_roots if target_node.cluster_id == "root" else target_node.children
            md.extend(
                _render_summary_table(
                    nodes=summary_targets[:15],
                    total_symbols=len(target_node.symbol_ids),
                    total_files=len(target_node.filepaths),
                    shared_hubs_count=len(hub_roots) if target_node.cluster_id == "root" else 0,
                    residuals_count=len(residual_roots) if target_node.cluster_id == "root" else 0,
                    macro_cycles_count=target_node.internal_macro_cycles,
                )
            )
            md.append("")
        else:
            if view_mode in ("tree", "both"):
                md.append("### Cluster Tree")
                md.append("```text")
                tree_root_lbl = f"{target_node.cluster_id} ({len(target_node.filepaths)} files, {len(target_node.symbol_ids):,} symbols)"
                md.append(tree_root_lbl)
                md.extend(
                    _render_tree(
                        target_node,
                        unit=unit_mode,
                        max_depth=depth_val,
                        current_depth=0,
                        filter_residuals=(target_node.cluster_id == "root"),
                    )
                )
                md.append("```")
                md.append("")

            if view_mode in ("mermaid", "both"):
                frontier = _collect_frontier(target_node, max_depth=depth_val)
                md.extend(_render_mermaid(frontier, unit=unit_mode, result=result))
                md.append("")

    if include_drift:
        md.extend(_render_drift(result.drift))
        md.append("")

    return "\n".join(md).rstrip()
