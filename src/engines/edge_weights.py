"""Shared edge weight calculation functions used across indexing and auditing."""
from typing import Dict, Any, Set, List, Optional


def calculate_weight(
    source_classifications: Optional[Dict[str, Any]],
    target_classifications: Optional[Dict[str, Any]],
    all_barriers: Set[str],
) -> float:
    """Calculate edge weight from source/target symbol classifications and barrier roles."""
    weight = 1.0

    if source_classifications:
        src_layer = source_classifications.get("layer")
        tgt_layer = target_classifications.get("layer") if target_classifications else None
        if src_layer and tgt_layer and src_layer == tgt_layer:
            weight *= 1.5

        src_tier = source_classifications.get("tier")
        tgt_tier = target_classifications.get("tier") if target_classifications else None
        if src_tier is not None and tgt_tier is not None:
            try:
                if int(src_tier) > int(tgt_tier):
                    weight *= 0.5
            except ValueError:
                pass

        src_role = source_classifications.get("architectural_role") or source_classifications.get("role") or ""
        if src_role in all_barriers:
            weight *= 0.3

    return weight


def collect_barriers(config: Any) -> Set[str]:
    """Collect all barrier values from automatic and manual fields in config."""
    barriers: Set[str] = set()
    for _, prefix_conf in config.items():
        auto_fields = prefix_conf.get("automatic_fields", {})
        manual_fields = prefix_conf.get("manual_fields", {})
        for _, field_conf in {**auto_fields, **manual_fields}.items():
            if field_conf.get("handler") == "propagation":
                barriers.update(field_conf.get("barriers") or [])
    return barriers


def update_edge_weights(
    repository,
    all_edges: List[Dict[str, Any]],
    symbol_classifications: Dict[str, Dict[str, Any]],
    config: Any,
) -> List[tuple]:
    """Recomputes and persists edge weights based on layer, tier, and barrier rules."""
    all_barriers = collect_barriers(config)

    updated_edges = []
    for edge in all_edges:
        src, tgt, rel = edge["source"], edge["target"], edge["relation"]
        src_data = symbol_classifications.get(src)
        tgt_data = symbol_classifications.get(tgt)
        src_fields = src_data["fields"] if src_data else None
        tgt_fields = tgt_data["fields"] if tgt_data else None
        weight = calculate_weight(src_fields, tgt_fields, all_barriers)
        updated_edges.append((weight, src, tgt, rel))

    if updated_edges and repository:
        repository.graph.update_edge_weights(updated_edges)
    return updated_edges
