"""Affinity graph construction, in-degree dampening, and integer index compaction."""
from collections import Counter, defaultdict
import math
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.exclusions import is_boilerplate, is_excluded
from utils.helpers import is_auxiliary_path, is_test_caller
from utils.symbol_id import parse_canonical_id

BASE_RELATION_WEIGHTS: Dict[str, float] = {
    "FFI_Binds": 2.5,
    "Implements": 2.0,
    "TypeDefinition": 2.0,
    "Inherits": 2.0,
    "parent_symbol": 2.0,
    "Injects": 1.2,
    "Calls": 1.0,
}


def build_affinity_graph(
    active_symbols_map: Dict[str, Dict[str, Any]],
    raw_edges: List[Dict[str, Any]],
    exclude_patterns: Optional[List[str]] = None,
    include_tests: bool = False,
) -> Dict[str, Any]:
    """
    Constructs:
    1. Integer-compacted index mappings (sym_to_id, id_to_sym)
    2. Directed dependency adjacency (dir_out_edges, dir_in_edges) without artificial polymorphic 2-cycles
    3. External target/caller maps tracking both symbol and target filepath
    4. Undirected affinity weights with inverse in-degree hub dampening and reciprocal bonus
    5. Soft undirected parent_symbol affinity edges (weight = 2.0, excluded from Tarjan SCC adjacency)
    6. Zero-degree unreferenced symbols separation (promoting active-child parent containers)
    """
    active_symbols = set(active_symbols_map.keys())

    # Exact canonical parent_symbol mapping
    parent_map: Dict[str, str] = {
        sym: p
        for sym, s_info in active_symbols_map.items()
        if (p := s_info.get("parent_symbol")) and p in active_symbols
    }

    dir_out_edges: Dict[str, Set[str]] = defaultdict(set)
    dir_in_edges: Dict[str, Set[str]] = defaultdict(set)
    external_targets_by_source: Dict[str, Dict[str, str]] = defaultdict(dict)
    external_callers_by_target: Dict[str, Dict[str, str]] = defaultdict(dict)
    dep_edge_weights: Dict[Tuple[str, str], float] = defaultdict(float)
    incident_dep_count: Counter = Counter()

    retained_edges_count = 0

    for e in raw_edges:
        src = e.get("source")
        tgt = e.get("target")
        rel = e.get("relation") or "Calls"
        src_fp = e.get("src_filepath") or ""
        tgt_fp = e.get("tgt_filepath") or ""

        if not src or not tgt or src == tgt:
            continue
        if src.startswith("local ") or tgt.startswith("local "):
            continue

        base_w = BASE_RELATION_WEIGHTS.get(rel, 1.0)

        if src in active_symbols:
            if tgt in active_symbols:
                incident_dep_count[src] += 1
                incident_dep_count[tgt] += 1
                dir_out_edges[src].add(tgt)
                dir_in_edges[tgt].add(src)
                dep_edge_weights[(src, tgt)] += base_w
                retained_edges_count += 1
            else:
                if is_boilerplate(tgt_fp) or is_excluded(tgt_fp, exclude_patterns):
                    continue
                if not include_tests and (is_auxiliary_path(tgt_fp) or is_test_caller(tgt, tgt_fp)):
                    continue

                incident_dep_count[src] += 1
                external_targets_by_source[src][tgt] = tgt_fp
                retained_edges_count += 1
        elif tgt in active_symbols:
            if is_boilerplate(src_fp) or is_excluded(src_fp, exclude_patterns):
                continue
            if not include_tests and (is_auxiliary_path(src_fp) or is_test_caller(src, src_fp)):
                continue

            incident_dep_count[tgt] += 1
            external_callers_by_target[tgt][src] = src_fp
            retained_edges_count += 1

    # Promote zero-edge parent containers whose children have incident dependency edges
    active_parent_containers: Set[str] = {
        parent_sym
        for child_sym, parent_sym in parent_map.items()
        if incident_dep_count[child_sym] > 0
    }

    unreferenced_symbols: List[Dict[str, Any]] = []
    clustered_symbols: List[str] = []
    for sym in sorted(active_symbols):
        if incident_dep_count[sym] == 0 and sym not in active_parent_containers:
            s_info = active_symbols_map[sym]
            unreferenced_symbols.append({
                "symbol": sym,
                "name": s_info.get("name") or parse_canonical_id(sym)[2] or sym,
                "filepath": s_info.get("filepath"),
                "kind": s_info.get("kind"),
                "start_line": s_info.get("start_line"),
            })
        else:
            clustered_symbols.append(sym)

    sym_to_id = {sym: i for i, sym in enumerate(clustered_symbols)}
    id_to_sym = {i: sym for i, sym in enumerate(clustered_symbols)}

    in_degree = {sym: len(dir_in_edges.get(sym, set())) for sym in clustered_symbols}

    undirected_aff: Dict[Tuple[int, int], float] = defaultdict(float)
    dampened_out_weights: Dict[Tuple[int, int], float] = defaultdict(float)
    dampened_in_weights: Dict[Tuple[int, int], float] = defaultdict(float)
    internal_adj_symbols: Dict[str, Set[str]] = defaultdict(set)

    pair_seen: Set[Tuple[int, int]] = set()
    for (src, tgt) in sorted(dep_edge_weights.keys()):
        w_base = dep_edge_weights[(src, tgt)]
        if src in sym_to_id and tgt in sym_to_id:
            u, v = sym_to_id[src], sym_to_id[tgt]
            pair_key = (min(u, v), max(u, v))
            pair_seen.add(pair_key)
            internal_adj_symbols[src].add(tgt)
            internal_adj_symbols[tgt].add(src)

            deg_in_tgt = max(1, in_degree.get(tgt, 1))
            w_dampened = w_base / math.sqrt(deg_in_tgt)
            dampened_out_weights[(u, v)] += w_dampened
            dampened_in_weights[(v, u)] += w_dampened

    for (u, v) in sorted(pair_seen):
        src, tgt = id_to_sym[u], id_to_sym[v]
        w_fwd = dep_edge_weights.get((src, tgt), 0.0)
        w_rev = dep_edge_weights.get((tgt, src), 0.0)

        deg_in_tgt = max(1, in_degree.get(tgt, 1))
        deg_in_src = max(1, in_degree.get(src, 1))

        w_prime_fwd = (w_fwd / math.sqrt(deg_in_tgt)) if w_fwd > 0 else 0.0
        w_prime_rev = (w_rev / math.sqrt(deg_in_src)) if w_rev > 0 else 0.0

        if w_fwd > 0 and w_rev > 0:
            undirected_aff[(u, v)] += 1.5 * (w_prime_fwd + w_prime_rev)
        else:
            undirected_aff[(u, v)] += (w_prime_fwd + w_prime_rev)

    # Soft parent_symbol edges (weight = 2.0, strictly undirected)
    parent_w = BASE_RELATION_WEIGHTS["parent_symbol"]
    for sym, parent in sorted(parent_map.items()):
        if sym in sym_to_id and parent in sym_to_id:
            u, v = sym_to_id[sym], sym_to_id[parent]
            pair_key = (min(u, v), max(u, v))
            undirected_aff[pair_key] += parent_w
            internal_adj_symbols[sym].add(parent)
            internal_adj_symbols[parent].add(sym)

    return {
        "clustered_symbols": clustered_symbols,
        "sym_to_id": sym_to_id,
        "id_to_sym": id_to_sym,
        "dir_out_edges": dir_out_edges,
        "dir_in_edges": dir_in_edges,
        "dampened_out_weights": dampened_out_weights,
        "dampened_in_weights": dampened_in_weights,
        "external_targets_by_source": external_targets_by_source,
        "external_callers_by_target": external_callers_by_target,
        "undirected_aff": undirected_aff,
        "internal_adj_symbols": internal_adj_symbols,
        "unreferenced_symbols": unreferenced_symbols,
        "retained_edges_count": retained_edges_count,
        "parent_map": parent_map,
    }
