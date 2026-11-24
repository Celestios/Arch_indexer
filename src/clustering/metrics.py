"""Unit-consistent containment scoring, boundary accounting, and transitive closure BFS."""
from collections import defaultdict, deque
from typing import Any, Dict, Optional, Set

from clustering.models import ClusterNode


def populate_index_and_leaves(
    node: ClusterNode,
    index_by_id: Dict[str, ClusterNode],
    symbol_to_leaf: Dict[str, str],
):
    """Builds index_by_id and maps each symbol to its finest leaf cluster ID."""
    index_by_id[node.cluster_id] = node
    if not node.children:
        for s in node.symbol_ids:
            symbol_to_leaf[s] = node.cluster_id
    else:
        for c in node.children:
            populate_index_and_leaves(c, index_by_id, symbol_to_leaf)


def compute_metrics(
    node: ClusterNode,
    unit: str,
    active_symbols_map: Dict[str, Dict[str, Any]],
    dir_out_edges: Dict[str, Set[str]],
    dir_in_edges: Dict[str, Set[str]],
    external_targets_by_source: Dict[str, Dict[str, str]],
    external_callers_by_target: Dict[str, Dict[str, str]],
    symbol_to_leaf: Dict[str, str],
):
    """Computes node-based containment, ext_dep_count, ext_caller_count, and closures uniformly for 'symbol' or 'file'."""
    for c in node.children:
        compute_metrics(
            c,
            unit,
            active_symbols_map,
            dir_out_edges,
            dir_in_edges,
            external_targets_by_source,
            external_callers_by_target,
            symbol_to_leaf,
        )

    by_file = unit == "file"
    owned_units: Set[str] = set(node.filepaths) if by_file else set(node.symbol_ids)

    def _unit_for_active(sym: str) -> Optional[str]:
        return active_symbols_map.get(sym, {}).get("filepath") if by_file else sym

    def _unit_for_external(sym: str, fp: str) -> Optional[str]:
        return (fp or None) if by_file else sym

    ext_targets: Set[str] = set()
    ext_callers: Set[str] = set()
    deps_by_cluster: Dict[str, Set[str]] = defaultdict(set)

    for s in node.symbol_ids:
        for tgt in dir_out_edges.get(s, set()):
            u_tgt = _unit_for_active(tgt)
            if u_tgt and u_tgt not in owned_units:
                ext_targets.add(u_tgt)
                deps_by_cluster[symbol_to_leaf.get(tgt, "external")].add(u_tgt)

        for tgt_sym, tgt_fp in external_targets_by_source.get(s, {}).items():
            u_tgt = _unit_for_external(tgt_sym, tgt_fp)
            if u_tgt and u_tgt not in owned_units:
                ext_targets.add(u_tgt)
                deps_by_cluster["external"].add(u_tgt)

        for src in dir_in_edges.get(s, set()):
            u_src = _unit_for_active(src)
            if u_src and u_src not in owned_units:
                ext_callers.add(u_src)

        for src_sym, src_fp in external_callers_by_target.get(s, {}).items():
            u_src = _unit_for_external(src_sym, src_fp)
            if u_src and u_src not in owned_units:
                ext_callers.add(u_src)

    node.ext_dep_count = len(ext_targets)
    node.ext_caller_count = len(ext_callers)
    total_units = len(owned_units) + node.ext_dep_count
    node.containment_pct = round((len(owned_units) / total_units * 100.0) if total_units > 0 else 100.0, 1)
    node.ext_deps_by_cluster = {k: sorted(v) for k, v in sorted(deps_by_cluster.items())}

    # Transitive closure via BFS using deque
    visited_units: Set[str] = set()
    bfs_visited_syms: Set[str] = set(node.symbol_ids)
    queue: deque = deque(node.symbol_ids)
    while queue:
        curr = queue.popleft()
        for nxt in dir_out_edges.get(curr, set()):
            if nxt not in bfs_visited_syms:
                bfs_visited_syms.add(nxt)
                queue.append(nxt)
                u_nxt = _unit_for_active(nxt)
                if u_nxt and u_nxt not in owned_units:
                    visited_units.add(u_nxt)
        for nxt_sym, nxt_fp in external_targets_by_source.get(curr, {}).items():
            u_nxt = _unit_for_external(nxt_sym, nxt_fp)
            if u_nxt and u_nxt not in owned_units:
                visited_units.add(u_nxt)

    node.closure_ext_count = len(visited_units)
