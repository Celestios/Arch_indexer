"""
Domain Enumerations and Color/Size Constants.
"""

from enum import Enum
from typing import Dict, List


class NodeType(str, Enum):
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    FIELD = "field"
    MODULE = "module"
    OCCURRENCE_DEF = "occurrence_def"
    OCCURRENCE_REF = "occurrence_ref"
    EXTERNAL = "external"
    LOCAL = "local"


class EdgeType(str, Enum):
    CALLS = "calls"
    DEFINES = "defines"
    REFERENCES = "references"
    REF_TO_DEF = "ref_to_def"
    CONTAINS = "contains"
    INHERITS = "inherits"
    LOCATED_IN = "located_in"


NODE_COLORS: Dict[NodeType, str] = {
    NodeType.FILE: "#38bdf8",            # Vivid Sky Blue
    NodeType.CLASS: "#a855f7",           # Vibrant Purple
    NodeType.FUNCTION: "#06b6d4",        # Cyan
    NodeType.METHOD: "#10b981",          # Emerald Green
    NodeType.CONSTRUCTOR: "#14b8a6",     # Teal
    NodeType.FIELD: "#f59e0b",           # Warm Amber
    NodeType.MODULE: "#6366f1",          # Indigo
    NodeType.OCCURRENCE_DEF: "#ec4899",  # Hot Pink
    NodeType.OCCURRENCE_REF: "#f97316",  # Bright Orange / Coral
    NodeType.EXTERNAL: "#64748b",        # Slate Gray
    NodeType.LOCAL: "#94a3b8",           # Muted Silver
}

NODE_SIZES: Dict[NodeType, int] = {
    NodeType.FILE: 14,
    NodeType.CLASS: 10,
    NodeType.MODULE: 9,
    NodeType.FUNCTION: 7,
    NodeType.METHOD: 6,
    NodeType.CONSTRUCTOR: 6,
    NodeType.FIELD: 5,
    NodeType.EXTERNAL: 5,
    NodeType.OCCURRENCE_DEF: 4,
    NodeType.OCCURRENCE_REF: 3,
    NodeType.LOCAL: 3,
}

EDGE_COLORS: Dict[EdgeType, str] = {
    EdgeType.CALLS: "#10b981",          # Green trace
    EdgeType.DEFINES: "#ec4899",        # Pink trace
    EdgeType.REFERENCES: "#f97316",     # Orange trace
    EdgeType.REF_TO_DEF: "#a855f7",     # Purple dashed trace
    EdgeType.CONTAINS: "#38bdf8",       # Sky blue
    EdgeType.INHERITS: "#eab308",       # Gold trace
    EdgeType.LOCATED_IN: "#475569",     # Dim slate
}

ZONE_PALETTE: List[str] = [
    "#38bdf8",  # Cyan
    "#10b981",  # Emerald
    "#a855f7",  # Purple
    "#f59e0b",  # Amber
    "#ec4899",  # Pink
    "#06b6d4",  # Teal-Cyan
    "#6366f1",  # Indigo
    "#84cc16",  # Lime
]
