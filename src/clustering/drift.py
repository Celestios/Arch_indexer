"""Architectural drift and filesystem/class boundary diagnostics."""
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from utils.helpers import demangle_scip_symbol
from clustering.models import ClusterNode, DriftReport


def _find_top_subsystem(node_id: str, index_by_id: Dict[str, ClusterNode]) -> str:
    """Finds top-level cluster ID under root (e.g. 'c2' for 'c2.1.3')."""
    curr = index_by_id.get(node_id)
    if not curr or curr.cluster_id == "root":
        return node_id
    while curr.parent_id and curr.parent_id != "root":
        curr = index_by_id.get(curr.parent_id, curr)
    return curr.cluster_id


def compute_drift_report(
    root: ClusterNode,
    symbol_to_leaf: Dict[str, str],
    active_symbols_map: Dict[str, Dict[str, Any]],
    index_by_id: Dict[str, ClusterNode],
) -> DriftReport:
    """Computes split_files, split_classes, misplaced_symbols, and scattered-cluster notes."""
    # Group symbols by file
    symbols_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s_info in active_symbols_map.values():
        fp = s_info.get("filepath")
        if fp:
            symbols_by_file[fp].append(s_info)

    split_files: List[Dict[str, Any]] = []
    misplaced_symbols: List[Dict[str, Any]] = []

    for fp, file_syms in sorted(symbols_by_file.items()):
        clustered = [s for s in file_syms if s["symbol"] in symbol_to_leaf]
        if len(clustered) < 2:
            continue

        # Check top-level subsystem purity first to prevent false-positive storms on cohesive sub-clusters
        top_counts = Counter(
            _find_top_subsystem(symbol_to_leaf[s["symbol"]], index_by_id)
            for s in clustered
        )
        leaf_counts = Counter(symbol_to_leaf[s["symbol"]] for s in clustered)
        total_m = len(clustered)

        dom_top, dom_top_count = top_counts.most_common(1)[0]
        top_purity = dom_top_count / total_m
        outside_top = total_m - dom_top_count

        dom_leaf, dom_leaf_count = leaf_counts.most_common(1)[0]
        leaf_purity = dom_leaf_count / total_m

        # Flag as split-brain only if fractured across distinct top-level subsystems
        if top_purity < 0.75 and outside_top >= 2:
            sorted_items = sorted(leaf_counts.items(), key=lambda x: (-x[1], x[0]))
            dist = {c: f"{cnt}s" for c, cnt in sorted_items}
            split_files.append({
                "filepath": fp,
                "purity_pct": round(top_purity * 100.0, 1),
                "dominant_cluster": dom_leaf,
                "distribution": dist,
            })
        elif leaf_purity >= 0.75 or top_purity >= 0.75:
            # File has a clear dominant cluster / subsystem; flag outliers
            dom_c = dom_leaf if leaf_purity >= 0.75 else dom_top
            for s in clustered:
                s_c = symbol_to_leaf[s["symbol"]]
                s_top = _find_top_subsystem(s_c, index_by_id)
                if (leaf_purity >= 0.75 and s_c != dom_c) or (leaf_purity < 0.75 and s_top != dom_top):
                    misplaced_symbols.append({
                        "symbol": s["symbol"],
                        "clean_symbol": s.get("clean_symbol") or demangle_scip_symbol(s["symbol"]),
                        "filepath": fp,
                        "assigned_cluster": s_c,
                        "file_cluster": dom_c,
                    })

    # Group misplaced symbols and annotate cluster drift_notes
    misplaced_counts: Dict[Tuple[str, str], int] = Counter()
    for ms in misplaced_symbols:
        misplaced_counts[(ms["assigned_cluster"], ms["filepath"])] += 1

    for (c_id, fp), cnt in sorted(misplaced_counts.items()):
        target_node = index_by_id.get(c_id)
        if target_node:
            sym_word = "symbol" if cnt == 1 else "symbols"
            target_node.drift_notes.append(f"misplaced: {cnt} {sym_word} physically in {fp}")

    # 2. Split-Brain Classes
    symbols_by_class: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s_info in active_symbols_map.values():
        p = s_info.get("parent_symbol")
        if p and p in active_symbols_map:
            symbols_by_class[p].append(s_info)

    split_classes: List[Dict[str, Any]] = []
    for cls_sym, members in sorted(symbols_by_class.items()):
        clustered_m = [s for s in members if s["symbol"] in symbol_to_leaf]
        if len(clustered_m) < 2:
            continue

        top_counts = Counter(
            _find_top_subsystem(symbol_to_leaf[s["symbol"]], index_by_id)
            for s in clustered_m
        )
        leaf_counts = Counter(symbol_to_leaf[s["symbol"]] for s in clustered_m)
        total_m = len(clustered_m)

        dom_top, dom_top_count = top_counts.most_common(1)[0]
        top_purity = dom_top_count / total_m

        if top_purity < 0.75:
            cls_info = active_symbols_map.get(cls_sym, {})
            fp = cls_info.get("filepath") or members[0].get("filepath")
            sorted_items = sorted(leaf_counts.items(), key=lambda x: (-x[1], x[0]))
            dist = {c: f"{cnt} methods" for c, cnt in sorted_items}
            split_classes.append({
                "class_symbol": cls_sym,
                "filepath": fp,
                "purity_pct": round(top_purity * 100.0, 1),
                "dominant_cluster": dom_top,
                "distribution": dist,
            })

    # 3. Scattered-cluster check on non-leaf clusters
    for c_id, node in index_by_id.items():
        if c_id == "root" or not node.filepaths:
            continue
        top_dirs: Counter = Counter()
        for fp in node.filepaths:
            norm = fp.replace("\\", "/").strip("/")
            # Strip filename to get directory parts only
            parts = norm.split("/")[:-1]
            for p in ("lib", "src", "packages"):
                if parts and parts[0] == p:
                    parts = parts[1:]
                    break
            if parts:
                top_dirs[parts[0]] += 1

        total_fps = len(node.filepaths)
        if len(top_dirs) >= 2 and total_fps >= 4:
            dom_dir_cnt = top_dirs.most_common(1)[0][1]
            if dom_dir_cnt / total_fps < 0.70:
                parts_str = ", ".join(f"{d} ({round(cnt / total_fps * 100)}%)" for d, cnt in top_dirs.most_common(3))
                node.drift_notes.append(f"scattered across: {parts_str}")

    return DriftReport(
        split_files=split_files,
        split_classes=split_classes,
        misplaced_symbols=misplaced_symbols,
    )
