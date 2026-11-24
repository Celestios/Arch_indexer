from collections import deque
import logging
from typing import Any, Dict, List

from engines.polymorphism import build_propagation_adjacency
from utils.arch_config import ArchConfig

logger = logging.getLogger(__name__)


class MetadataPropagator:
    """Propagates symbol metadata downstream or upstream on the call graph via worklist fixed-point."""

    def run_propagation(
        self,
        symbol_classifications: Dict[str, Dict[str, Any]],
        all_edges: List[Dict[str, Any]],
        config: ArchConfig,
    ) -> Dict[tuple, str]:
        propagation_fields = {}
        for _, prefix_conf in config.items():
            for field_name, field_conf in prefix_conf.automatic_fields.items():
                if field_conf.get("handler") == "propagation":
                    propagation_fields[field_name] = {
                        "direction": field_conf.get("propagation_direction", "upstream"),
                        "weights": field_conf.get("weights") or {},
                        "barriers": set(field_conf.get("barriers") or []),
                        "barrier_field": field_conf.barrier_field,
                        "values": field_conf.get("values") or [],
                        "default": field_conf.get("default"),
                    }

        if not propagation_fields:
            return {}

        adj_forward, adj_backward = build_propagation_adjacency(all_edges, symbol_classifications)

        propagation_sources: Dict[tuple, str] = {}

        for field_name, p_cfg in propagation_fields.items():
            direction = p_cfg["direction"]
            weights = p_cfg["weights"] or {val: idx for idx, val in enumerate(p_cfg["values"])}
            barriers = p_cfg["barriers"]
            barrier_field = p_cfg["barrier_field"]
            default_val = p_cfg["default"]

            def get_weight(val, _w=weights):
                if val is None or val == "Unknown":
                    return -1
                return _w.get(val, 0)

            _adj = adj_backward if direction == "upstream" else adj_forward

            worklist = []
            visited = set()
            for sym, data in symbol_classifications.items():
                val = data["fields"].get(field_name, default_val)
                if val is not None and val != default_val:
                    worklist.append(sym)
                    visited.add(sym)

            queue = deque(worklist)
            iterations = 0
            max_iterations = max(10000, len(symbol_classifications) * 10)

            while queue and iterations < max_iterations:
                n = queue.popleft()
                visited.discard(n)
                iterations += 1

                n_val = symbol_classifications[n]["fields"].get(field_name, default_val)
                n_weight = get_weight(n_val)

                for m in _adj.get(n, ()):
                    m_barrier_val = symbol_classifications[m]["fields"].get(barrier_field, default_val)
                    if m_barrier_val in barriers:
                        continue

                    m_val = symbol_classifications[m]["fields"].get(field_name, default_val)
                    if n_weight > get_weight(m_val):
                        symbol_classifications[m]["fields"][field_name] = n_val
                        propagation_sources[(m, field_name)] = n
                        if m not in visited:
                            queue.append(m)
                            visited.add(m)

            if queue and iterations >= max_iterations:
                logger.warning(
                    "Worklist propagation for field '%s' reached maximum iteration cap (%d) before reaching a fixed point.",
                    field_name,
                    max_iterations,
                )

        return propagation_sources
