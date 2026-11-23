"""Unit-consistent containment scoring, boundary accounting, and transitive closure BFS."""
from collections import defaultdict, deque
from typing import Any, Dict, List, Set

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
    """Computes node-based containment, ext_dep_count, ext_caller_count, and closures."""
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

    if unit == "file":
        s_files = set(node.filepaths)
        ext_target_files: Set[str] = set()
        deps_by_cluster: Dict[str, Set[str]] = defaultdict(set)

        for s in node.symbol_ids:
            for tgt in dir_out_edges.get(s, set()):
                tgt_fp = active_symbols_map.get(tgt, {}).get("filepath")
                if tgt_fp and tgt_fp not in s_files:
                    ext_target_files.add(tgt_fp)
                    c_id = symbol_to_leaf.get(tgt, "external")
                    deps_by_cluster[c_id].add(tgt_fp)

            for tgt_sym, tgt_fp in external_targets_by_source.get(s, {}).items():
                if tgt_fp and tgt_fp not in s_files:
                    ext_target_files.add(tgt_fp)
                    deps_by_cluster["external"].add(tgt_fp)

        ext_caller_files: Set[str] = set()
        for s in node.symbol_ids:
            for src in dir_in_edges.get(s, set()):
                src_fp = active_symbols_map.get(src, {}).get("filepath")
                if src_fp and src_fp not in s_files:
                    ext_caller_files.add(src_fp)

            for src_sym, src_fp in external_callers_by_target.get(s, {}).items():
                if src_fp and src_fp not in s_files:
                    ext_caller_files.add(src_fp)

        node.ext_dep_count = len(ext_target_files)
        node.ext_caller_count = len(ext_caller_files)
        total_units = len(s_files) + node.ext_dep_count
        node.containment_pct = round((len(s_files) / total_units * 100.0) if total_units > 0 else 100.0, 1)
        node.ext_deps_by_cluster = {k: sorted(list(v)) for k, v in sorted(deps_by_cluster.items())}

        # Transitive closure in files via BFS using deque
        visited_files: Set[str] = set()
        bfs_visited_syms = set(node.symbol_ids)
        queue: deque = deque(node.symbol_ids)
        while queue:
            curr = queue.popleft()
            for nxt in dir_out_edges.get(curr, set()):
                if nxt not in bfs_visited_syms:
                    bfs_visited_syms.add(nxt)
                    queue.append(nxt)
                    nxt_fp = active_symbols_map.get(nxt, {}).get("filepath")
                    if nxt_fp and nxt_fp not in s_files:
                        visited_files.add(nxt_fp)
            for nxt_sym, nxt_fp in external_targets_by_source.get(curr, {}).items():
                if nxt_fp and nxt_fp not in s_files:
                    visited_files.add(nxt_fp)
        node.closure_ext_count = len(visited_files)

    else:
        # unit == "symbol"
        s_syms = set(node.symbol_ids)
        ext_targets: Set[str] = set()
        deps_by_cluster = defaultdict(set)

        for s in node.symbol_ids:
            for tgt in dir_out_edges.get(s, set()):
                if tgt not in s_syms:
                    ext_targets.add(tgt)
                    c_id = symbol_to_leaf.get(tgt, "external")
                    deps_by_cluster[c_id].add(tgt)

            for tgt_sym, tgt_fp in external_targets_by_source.get(s, {}).items():
                if tgt_sym not in s_syms:
                    ext_targets.add(tgt_sym)
                    deps_by_cluster["external"].add(tgt_sym)

        ext_callers: Set[str] = set()
        for s in node.symbol_ids:
            for src in dir_in_edges.get(s, set()):
                if src not in s_syms:
                    ext_callers.add(src)

            for src_sym, src_fp in external_callers_by_target.get(s, {}).items():
                if src_sym not in s_syms:
                    ext_callers.add(src_sym)

        node.ext_dep_count = len(ext_targets)
        node.ext_caller_count = len(ext_callers)
        total_units = len(s_syms) + node.ext_dep_count
        node.containment_pct = round((len(s_syms) / total_units * 100.0) if total_units > 0 else 100.0, 1)
        node.ext_deps_by_cluster = {k: sorted(list(v)) for k, v in sorted(deps_by_cluster.items())}

        # Transitive closure in symbols via BFS using deque
        visited_syms: Set[str] = set()
        queue = deque(ext_targets)
        for item in ext_targets:
            visited_syms.add(item)
        while queue:
            curr = queue.popleft()
            for nxt in dir_out_edges.get(curr, set()):
                if nxt not in s_syms and nxt not in visited_syms:
                    visited_syms.add(nxt)
                    queue.append(nxt)
            for nxt_sym in external_targets_by_source.get(curr, {}).keys():
                if nxt_sym not in s_syms and nxt_sym not in visited_syms:
                    visited_syms.add(nxt_sym)
        node.closure_ext_count = len(visited_syms)
