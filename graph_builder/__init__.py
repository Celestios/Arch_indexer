"""
Graph Builder Package (SRP Modular Architecture).
"""

from .config import CircuitConfig, LayoutConfig, SizerConfig, RoutingConfig
from .ingestion.db_reader import DatabaseReader
from .ingestion.scip_parser import ScipParser
from .domain.types import NodeType, EdgeType, NODE_COLORS, NODE_SIZES, EDGE_COLORS
from .domain.entities import GraphNode, GraphEdge
from .domain.model import GraphModel
from .layout.spatial_layout import SpatialLayoutEngine
from .layout.circuit_layout import CircuitLayoutEngine
from .layout.zone_classifier import TopologicalZoneClassifier
from .layout.package_sizer import PackageSizer
from .routing.channel_router import OrthogonalChannelRouter
from .serialization.compressor import compress_circuit_data
from .renderer.html_generator import HtmlGraphGenerator
from .cli import build_graph_html

__all__ = [
    "CircuitConfig",
    "LayoutConfig",
    "SizerConfig",
    "RoutingConfig",
    "DatabaseReader",
    "ScipParser",
    "NodeType",
    "EdgeType",
    "NODE_COLORS",
    "NODE_SIZES",
    "EDGE_COLORS",
    "GraphNode",
    "GraphEdge",
    "GraphModel",
    "SpatialLayoutEngine",
    "CircuitLayoutEngine",
    "TopologicalZoneClassifier",
    "PackageSizer",
    "OrthogonalChannelRouter",
    "compress_circuit_data",
    "HtmlGraphGenerator",
    "build_graph_html",
]
