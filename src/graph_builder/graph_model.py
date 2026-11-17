"""
Backwards-compatible facade re-exporting Domain types, entities, and GraphModel.
"""

from .domain.types import NodeType, EdgeType, NODE_COLORS, NODE_SIZES, EDGE_COLORS
from .domain.entities import GraphNode, GraphEdge
from .domain.model import GraphModel

__all__ = [
    "NodeType",
    "EdgeType",
    "NODE_COLORS",
    "NODE_SIZES",
    "EDGE_COLORS",
    "GraphNode",
    "GraphEdge",
    "GraphModel",
]
