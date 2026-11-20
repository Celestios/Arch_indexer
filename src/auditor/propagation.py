import sys
from typing import Dict, List, Any
from collections import deque

class MetadataPropagator:
    """
    Propagates symbol metadata downstream or upstream on the call graph using LPA or iterative worklist algorithms.
    """

    def run_propagation(
        self,
        symbol_classifications: Dict[str, Dict[str, Any]],
        all_edges: List[Dict[str, Any]],
        config: Dict[str, Any]
    ) -> Dict[tuple, str]:
        """
        Runs the dynamic fixed-point worklist propagation algorithm on the call graph.
        Returns a predecessor mapping (child, field_name) -> parent to trace the origin of values.
        """
        propagation_fields = {}
        for prefix, prefix_conf in config.items():
            auto_fields = prefix_conf.get("automatic_fields", {})
            for field_name, field_conf in auto_fields.items():
                if field_conf.get("handler") == "propagation":
                    propagation_fields[field_name] = {
                        "direction": field_conf.get("propagation_direction", "upstream"),
                        "weights": field_conf.get("weights") or {},
                        "barriers": set(field_conf.get("barriers") or []),
                        "barrier_field": field_conf.get("barrier_field", "architectural_role") or "architectural_role",
                        "values": field_conf.get("values") or [],
                        "default": field_conf.get("default")
                    }

        if not propagation_fields:
            return {}

        # Build adjacency lists for the call graph
        adj_forward = {}
        adj_backward = {}
        for edge in all_edges:
            src = edge["source"]
            tgt = edge["target"]
            if src in symbol_classifications and tgt in symbol_classifications:
                adj_forward.setdefault(src, set()).add(tgt)
                adj_backward.setdefault(tgt, set()).add(src)

        # Tracks predecessor mappings: (child, field_name) -> parent
        propagation_sources = {}

        for field_name, p_cfg in propagation_fields.items():
            direction = p_cfg["direction"]
            weights = p_cfg["weights"]
            barriers = p_cfg["barriers"]
            barrier_field = p_cfg.get("barrier_field") or "architectural_role"
            values = p_cfg["values"]
            default_val = p_cfg["default"]

            # Map values to integer weights (priority)
            if not weights:
                weights = {val: idx for idx, val in enumerate(values)}

            def get_weight(val):
                if val is None or val == "Unknown":
                    return -1
                return weights.get(val, 0)

            # Determine neighbors traversal function
            # Use default argument binding to avoid late-binding closure over mutable dict
            if direction == "upstream":
                _adj = adj_backward
                get_neighbors = lambda n, _a=_adj: _a.get(n, [])
            else:
                _adj = adj_forward
                get_neighbors = lambda n, _a=_adj: _a.get(n, [])

            # Initialize worklist with all symbols having non-default values
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

                for m in get_neighbors(n):
                    # Check barriers on neighbor node `m`
                    m_barrier_val = symbol_classifications[m]["fields"].get(barrier_field, default_val)
                    if m_barrier_val in barriers:
                        continue

                    m_val = symbol_classifications[m]["fields"].get(field_name, default_val)
                    m_weight = get_weight(m_val)

                    if n_weight > m_weight:
                        symbol_classifications[m]["fields"][field_name] = n_val
                        propagation_sources[(m, field_name)] = n
                        if m not in visited:
                            queue.append(m)
                            visited.add(m)

            if queue and iterations >= max_iterations:
                print(
                    f"[MetadataPropagator] Warning: Worklist propagation for field '{field_name}' "
                    f"reached maximum iteration cap ({max_iterations}) before reaching a fixed point.",
                    file=sys.stderr
                )

        return propagation_sources
