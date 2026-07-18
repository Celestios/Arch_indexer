from typing import Dict, List, Any

from db.repository import Repository
from engines.edge_weights import EdgeWeightCalculator


class EdgeWeightUpdater:
    """Computes and updates edge weights based on symbol classifications."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def update_edge_weights(self, all_edges: List[Dict[str, Any]], symbol_classifications: Dict[str, Dict[str, Any]], config: Dict[str, Any]):
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

        if updated_edges:
            self.repository.edges.update_edge_weights_bulk(updated_edges)
