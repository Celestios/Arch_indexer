"""Deterministic cluster naming and dominant directory heuristics."""
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.helpers import demangle_scip_symbol
from clustering.models import ClusterNode


def compute_dominant_dir(filepaths: Tuple[str, ...], symbol_fps: List[str]) -> Optional[str]:
    """Finds deepest directory prefix containing >= 50% of symbols, stripped of lib/ or src/."""
    total = len(symbol_fps)
    if total == 0:
        return None
    prefix_counts: Counter = Counter()
    for fp in symbol_fps:
        norm = fp.replace("\\", "/").strip("/")
        parts = norm.split("/")[:-1]
        for l in range(1, len(parts) + 1):
            prefix_counts["/".join(parts[:l])] += 1

    qualifying = [p for p, cnt in prefix_counts.items() if cnt >= 0.5 * total]
    if not qualifying:
        # Fall back to plurality directory (directory containing the most symbols)
        if prefix_counts:
            # Sort by count desc, then path depth desc
            plurality = sorted(
                prefix_counts.items(),
                key=lambda x: (x[1], len(x[0].split("/")), len(x[0])),
                reverse=True,
            )[0][0]
            qualifying = [plurality]
        elif filepaths:
            p = filepaths[0].replace("\\", "/").strip("/").split("/")[:-1]
            if p:
                qualifying = ["/".join(p)]
    if not qualifying:
        return None

    qualifying.sort(key=lambda p: (len(p.split("/")), len(p)), reverse=True)
    deepest = qualifying[0]
    short = deepest
    for prefix in ("lib/", "src/", "packages/"):
        if short.startswith(prefix):
            short = short[len(prefix):]
            break
    return short or deepest


def find_top_internal_hub(
    symbol_ids: Tuple[str, ...],
    internal_adj: Dict[str, Set[str]],
    active_symbols_map: Dict[str, Dict[str, Any]],
) -> str:
    """Finds highest internal-degree symbol inside cluster."""
    if not symbol_ids:
        return ""
    if len(symbol_ids) == 1:
        s_info = active_symbols_map.get(symbol_ids[0], {})
        return s_info.get("clean_symbol") or demangle_scip_symbol(symbol_ids[0])

    sym_set = set(symbol_ids)
    scored: List[Tuple[int, str, str]] = []
    for s in symbol_ids:
        neighbors = internal_adj.get(s, set())
        deg = len(neighbors & sym_set)
        s_info = active_symbols_map.get(s, {})
        clean = s_info.get("clean_symbol") or demangle_scip_symbol(s)
        scored.append((deg, s, clean))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][2]


def derive_cluster_name(
    node: ClusterNode,
    active_symbols_map: Dict[str, Dict[str, Any]],
    internal_adj: Dict[str, Set[str]],
) -> Tuple[str, Optional[str]]:
    """Derives human-readable cluster name according to specification."""
    if len(node.symbol_ids) == 1:
        s = node.symbol_ids[0]
        s_info = active_symbols_map.get(s, {})
        clean = s_info.get("clean_symbol") or demangle_scip_symbol(s)
        return clean, None

    symbol_fps = [
        active_symbols_map[s].get("filepath", "")
        for s in node.symbol_ids
        if s in active_symbols_map and active_symbols_map[s].get("filepath")
    ]
    dom_dir = compute_dominant_dir(node.filepaths, symbol_fps)

    # Multi-symbol, 1-file cluster: <ClassName> if all symbols belong to that class, else filename stem
    if len(node.filepaths) == 1:
        fp = node.filepaths[0]
        # Collect candidate enclosing classes
        all_classes = {
            s for s in node.symbol_ids
            if active_symbols_map.get(s, {}).get("kind") in ("Class", "Struct", "Interface", "Trait")
        }
        all_parents = {
            active_symbols_map.get(s, {}).get("parent_symbol")
            for s in node.symbol_ids
            if active_symbols_map.get(s, {}).get("parent_symbol")
        }
        candidate_classes = all_classes | all_parents
        if len(candidate_classes) == 1:
            cls_sym = next(iter(candidate_classes))
            # Verify EVERY symbol belongs to cls_sym
            all_belong = all(
                s == cls_sym or active_symbols_map.get(s, {}).get("parent_symbol") == cls_sym
                for s in node.symbol_ids
            )
            if all_belong:
                cls_info = active_symbols_map.get(cls_sym, {})
                cls_name = cls_info.get("clean_symbol") or demangle_scip_symbol(cls_sym)
                return cls_name, dom_dir
        stem = Path(fp.replace("\\", "/")).stem
        return stem, dom_dir

    # Multi-file cluster: <dominant_dir_short> [<top_internal_hub>]
    top_hub = find_top_internal_hub(node.symbol_ids, internal_adj, active_symbols_map)
    if dom_dir:
        return f"{dom_dir} [{top_hub}]", dom_dir
    return f"[{top_hub}]", dom_dir
