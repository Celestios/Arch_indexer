"""
Domain Entities for Graph Nodes, Edges, and File Packages.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple
from .types import NodeType, EdgeType


@dataclass
class GraphNode:
    id: str
    label: str
    type: NodeType
    color: str
    val: float
    group: str
    filepath: Optional[str] = None
    line: Optional[int] = None
    col: Optional[int] = None
    end_line: Optional[int] = None
    signature: Optional[str] = None
    docstring: Optional[str] = None
    raw_symbol: Optional[str] = None
    code: Optional[str] = None
    is_external: bool = False
    is_local: bool = False
    is_hub: bool = False
    parent_class: Optional[str] = None
    ports: Dict[str, Any] = field(default_factory=lambda: {"inputs": [], "output": None})
    in_degree: int = 0
    out_degree: int = 0
    x: int = 0
    y: int = 0
    width: int = 12
    height: int = 12
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value if isinstance(self.type, NodeType) else self.type
        return d


@dataclass
class GraphEdge:
    source: str
    target: str
    type: EdgeType
    color: str
    relation: str
    weight: float = 1.0
    dashed: bool = False
    call_sites: List[Tuple[int, int]] = field(default_factory=list)
    call_count: int = 1
    is_hub_stub: bool = False
    hub_stub_target: Optional[str] = None
    waypoints: List[int] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value if isinstance(self.type, EdgeType) else self.type
        return d
