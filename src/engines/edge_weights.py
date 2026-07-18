from typing import Dict, Any, Set


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
