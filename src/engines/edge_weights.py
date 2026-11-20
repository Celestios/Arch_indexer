from typing import Dict, Any, Set, List, Optional


class EdgeWeightCalculator:
    """
    Shared edge weight calculation logic.
    Used by both SCIP ingester and Auditor to compute consistent edge weights.
    """

    @staticmethod
    def calculate_weight(
        source_classifications: Dict[str, Any],
        target_classifications: Dict[str, Any],
        all_barriers: Set[str]
    ) -> float:
        """
        Calculate edge weight based on source and target symbol classifications.

        Args:
            source_classifications: Source symbol's fields dict
            target_classifications: Target symbol's fields dict (or None)
            all_barriers: Set of barrier values that reduce weight

        Returns:
            Weight value (default 1.0)
        """
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

    @staticmethod
    def collect_barriers(config: Dict[str, Any]) -> Set[str]:
        """Collect all barrier values from config automatic_fields and manual_fields."""
        barriers = set()
        for prefix, prefix_conf in config.items():
            auto_fields = prefix_conf.get("automatic_fields", {})
            manual_fields = prefix_conf.get("manual_fields", {})
            for field_name, field_conf in {**auto_fields, **manual_fields}.items():
                if field_conf.get("handler") == "propagation":
                    barriers.update(field_conf.get("barriers") or [])
        return barriers


def update_edge_weights(
    repository,
    all_edges: List[Dict[str, Any]],
    symbol_classifications: Dict[str, Dict[str, Any]],
    config: Dict[str, Any]
) -> List[tuple]:
    """Updates edge weights based on layer, tier, and barrier rules."""
    all_barriers = EdgeWeightCalculator.collect_barriers(config)

    updated_edges = []
    for edge in all_edges:
        src, tgt, rel = edge["source"], edge["target"], edge["relation"]
        src_data = symbol_classifications.get(src)
        tgt_data = symbol_classifications.get(tgt)

        src_fields = src_data["fields"] if src_data else None
        tgt_fields = tgt_data["fields"] if tgt_data else None

        weight = EdgeWeightCalculator.calculate_weight(src_fields, tgt_fields, all_barriers)
        updated_edges.append((weight, src, tgt, rel))

    if updated_edges and repository:
        repository.graph.update_edge_weights_bulk(updated_edges)
    return updated_edges


class EdgeWeightUpdater:
    """Computes and updates edge weights based on symbol classifications."""

    def __init__(self, repository):
        self.repository = repository

    def update_edge_weights(
        self,
        all_edges: List[Dict[str, Any]],
        symbol_classifications: Dict[str, Dict[str, Any]],
        config: Dict[str, Any]
    ) -> List[tuple]:
        return update_edge_weights(self.repository, all_edges, symbol_classifications, config)
