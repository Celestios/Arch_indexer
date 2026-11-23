"""Pipeline coordinator for hierarchical clustering and architectural decomposition."""
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from utils.exclusions import (
    is_boilerplate,
    is_excluded,
    load_exclude_patterns,
    load_include_dirs,
)
from utils.helpers import is_auxiliary_path, is_test_caller, normalize_scopes

from clustering.models import ClusterNode, ClusterHierarchyResult
from clustering.affinity import build_affinity_graph
from clustering.scc import iterative_tarjan_scc
from clustering.aggregator import run_hierarchical_aggregation
from clustering.naming import derive_cluster_name
from clustering.metrics import populate_index_and_leaves, compute_metrics
from clustering.drift import compute_drift_report


def build_cluster_hierarchy(
    repository,
    project_root: Path,
    scope: Optional[Union[str, List[str]]] = None,
    language: Optional[str] = None,
    include_tests: bool = False,
    unit: str = "symbol",
) -> ClusterHierarchyResult:
    """
    Main entry point for parameter-free hierarchical clustering.
    Builds emergent cluster tree across passes L = 1..8 with dominance-gated hub ejection.
    """
    project_root = Path(project_root).resolve()

    # Ingress hygiene: resolve scope
    scope_list = normalize_scopes(scope)
    if scope_list is None:
        try:
            inc_dirs = load_include_dirs(project_root)
            if inc_dirs:
                scope_list = sorted(list(inc_dirs))
        except Exception:
            scope_list = None

    # 1. Fetch graph projection from DuckDB
    raw_data = repository.analytics.get_cluster_graph_data(
        language=language,
        scope_prefixes=scope_list,
    )
    raw_symbols = raw_data.get("symbols", [])
    raw_edges = raw_data.get("edges", [])

    # 2. Ingress filtering
    exclude_patterns = load_exclude_patterns(project_root)
    active_symbols_map: Dict[str, Dict[str, Any]] = {}
    for s in raw_symbols:
        sym = s.get("symbol")
        fp = s.get("filepath")
        if not sym or not fp:
            continue
        if sym.startswith("local "):
            continue
        if is_boilerplate(fp):
            continue
        if is_excluded(fp, exclude_patterns):
            continue
        if not include_tests:
            if is_auxiliary_path(fp) or is_test_caller(sym, fp):
                continue
        active_symbols_map[sym] = s

    # 3. Build affinity graph
    graph_data = build_affinity_graph(
        active_symbols_map=active_symbols_map,
        raw_edges=raw_edges,
        exclude_patterns=exclude_patterns,
        include_tests=include_tests,
    )
    clustered_symbols = graph_data["clustered_symbols"]
    sym_to_id = graph_data["sym_to_id"]
    id_to_sym = graph_data["id_to_sym"]
    dir_out_edges = graph_data["dir_out_edges"]
    dir_in_edges = graph_data["dir_in_edges"]
    external_targets_by_source = graph_data["external_targets_by_source"]
    external_callers_by_target = graph_data["external_callers_by_target"]
    undirected_aff = graph_data["undirected_aff"]
    raw_dep_weight = graph_data["raw_dep_weight"]
    internal_adj_symbols = graph_data["internal_adj_symbols"]
    unreferenced_symbols = graph_data["unreferenced_symbols"]

    # 4. Stage 2: Iterative Tarjan SCC over directed dependency edges
    tarjan_adj: Dict[int, List[int]] = defaultdict(list)
    for src in sorted(dir_out_edges.keys()):
        if src in sym_to_id:
            u = sym_to_id[src]
            for tgt in sorted(dir_out_edges[src]):
                if tgt in sym_to_id:
                    tarjan_adj[u].append(sym_to_id[tgt])

    sccs = iterative_tarjan_scc(list(range(len(clustered_symbols))), tarjan_adj)

    # Form initial Level-0 atomic clusters / singletons
    initial_nodes: List[ClusterNode] = []
    for scc in sccs:
        member_syms = tuple(sorted(id_to_sym[i] for i in scc))
        member_fps = tuple(sorted({
            active_symbols_map[s]["filepath"]
            for s in member_syms
            if active_symbols_map[s].get("filepath")
        }))
        is_cycle = len(member_syms) >= 2
        is_singleton = len(member_syms) == 1
        node = ClusterNode(
            cluster_id="",
            name="",
            level=0,
            parent_id=None,
            symbol_ids=member_syms,
            filepaths=member_fps,
            is_cycle=is_cycle,
            is_singleton=is_singleton,
        )
        initial_nodes.append(node)

    initial_nodes.sort(key=lambda c: (-len(c.symbol_ids), min(c.symbol_ids) if c.symbol_ids else ""))

    # 5. Stage 3: Iterative bottom-up aggregation
    root = run_hierarchical_aggregation(
        initial_nodes=initial_nodes,
        sym_to_id=sym_to_id,
        undirected_aff=undirected_aff,
        raw_dep_weight=raw_dep_weight,
        dir_in_edges=dir_in_edges,
        max_passes=8,
    )

    # 6. Indexing and Leaf mapping
    index_by_id: Dict[str, ClusterNode] = {}
    symbol_to_leaf: Dict[str, str] = {}
    populate_index_and_leaves(root, index_by_id, symbol_to_leaf)

    # 7. Automatic cluster naming
    for c_id, node in index_by_id.items():
        if c_id == "root":
            continue
        node_name, dom_dir = derive_cluster_name(node, active_symbols_map, internal_adj_symbols)
        node.name = node_name
        node.dominant_dir = dom_dir

    # 8. Compute node-based containment metrics
    compute_metrics(
        root,
        unit=unit,
        active_symbols_map=active_symbols_map,
        dir_out_edges=dir_out_edges,
        dir_in_edges=dir_in_edges,
        external_targets_by_source=external_targets_by_source,
        external_callers_by_target=external_callers_by_target,
        symbol_to_leaf=symbol_to_leaf,
    )

    # 9. Compute drift report
    drift = compute_drift_report(root, symbol_to_leaf, active_symbols_map, index_by_id)

    total_symbols = len(active_symbols_map)
    total_files = len({s["filepath"] for s in active_symbols_map.values() if s.get("filepath")})
    total_edges = graph_data.get("retained_edges_count", len(raw_edges))

    return ClusterHierarchyResult(
        root=root,
        index_by_id=index_by_id,
        symbol_to_leaf=symbol_to_leaf,
        unreferenced_symbols=unreferenced_symbols,
        drift=drift,
        total_symbols=total_symbols,
        total_files=total_files,
        total_edges=total_edges,
    )
