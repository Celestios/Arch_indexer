"""Data models for hierarchical graph clustering and drift analysis."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ClusterNode:
    cluster_id: str                        # "root", "c1", "c1.2", etc.
    name: str                              # Emergent human-readable name
    level: int                             # 0 = leaf/SCC, increasing toward root
    parent_id: Optional[str]
    children: List["ClusterNode"] = field(default_factory=list)
    symbol_ids: Tuple[str, ...] = ()       # All member symbols (recursive)
    filepaths: Tuple[str, ...] = ()        # Unique files touched (sorted)
    is_cycle: bool = False                 # True if Level-0 Tarjan SCC (size >= 2)
    is_singleton: bool = False             # True if 1-symbol cluster (e.g., shared hub)
    dominant_dir: Optional[str] = None
    containment_pct: float = 100.0         # |S| / (|S| + |B(S)|) * 100
    ext_dep_count: int = 0                 # |B(S)| unique external targets
    ext_caller_count: int = 0              # |I(S)| unique external callers
    closure_ext_count: int = 0             # |R(S) \ S|
    ext_deps_by_cluster: Dict[str, List[str]] = field(default_factory=dict)
    drift_notes: List[str] = field(default_factory=list)
    instability: float = 0.0               # Ce / (Ca + Ce), 0.0 when Ca + Ce == 0
    macro_cycle_peers: Tuple[str, ...] = ()  # Sorted sibling cluster_ids in same quotient SCC
    cyclic_ext_dep_count: int = 0          # Unique external targets landing in macro_cycle_peers
    internal_macro_cycles: int = 0         # Count of non-trivial quotient SCCs among direct children


@dataclass
class DriftReport:
    split_files: List[Dict[str, Any]]      # [{filepath, purity_pct, distribution}]
    split_classes: List[Dict[str, Any]]    # [{class_symbol, filepath, purity_pct, distribution}]
    misplaced_symbols: List[Dict[str, Any]] # [{symbol, filepath, assigned_cluster, file_cluster}]


@dataclass
class ClusterHierarchyResult:
    root: ClusterNode
    index_by_id: Dict[str, ClusterNode]    # Fast O(1) zoom lookup
    symbol_to_leaf: Dict[str, str]         # symbol -> finest cluster_id
    unreferenced_symbols: List[Dict[str, Any]]
    drift: DriftReport
    total_symbols: int
    total_files: int
    total_edges: int
