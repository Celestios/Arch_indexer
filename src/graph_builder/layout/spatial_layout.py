"""
Radial Spatial Layout Engine (Fallback / Force-Graph Initializer).
"""

import math
from typing import Dict, List, Any


class SpatialLayoutEngine:
    """
    Computes modular radial coordinates for nodes grouped by directory clusters.
    """

    def __init__(self, cluster_radius: float = 600.0, node_spacing: float = 40.0):
        self.cluster_radius = cluster_radius
        self.node_spacing = node_spacing

    def apply_layout(self, graph_dict: Dict[str, Any], static: bool = False) -> Dict[str, Any]:
        nodes = graph_dict.get("nodes", [])
        if not nodes:
            return graph_dict

        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            group = node.get("group") or "root"
            top_group = group.split("/")[0] if "/" in group else group
            clusters.setdefault(top_group, []).append(node)

        cluster_names = sorted(clusters.keys())
        num_clusters = len(cluster_names)
        angle_step = (2 * math.pi) / max(num_clusters, 1)

        for i, cname in enumerate(cluster_names):
            cluster_angle = i * angle_step
            cx = self.cluster_radius * math.cos(cluster_angle)
            cy = self.cluster_radius * math.sin(cluster_angle)
            cluster_nodes = clusters[cname]

            sym_angle_step = (2 * math.pi) / max(len(cluster_nodes), 1)
            sym_ring_radius = 180.0 + min(len(cluster_nodes) * 2.5, 320.0)

            for si, snode in enumerate(cluster_nodes):
                sa = si * sym_angle_step
                sx = cx + sym_ring_radius * math.cos(sa)
                sy = cy + sym_ring_radius * math.sin(sa)
                snode["x"] = sx
                snode["y"] = sy
                if static:
                    snode["fx"] = sx
                    snode["fy"] = sy

        return graph_dict
