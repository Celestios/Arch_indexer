"""
Canonical dynamic-dispatch and polymorphic resolution contract shared across
AnalyticsStore (BFS blast radius), ContextCompiler (weighted Dijkstra), and
MetadataPropagator (architectural boundary propagation).

Symmetry invariant:
  - Standard edges (relation != 'Implements'):
      downstream: source -> target
      upstream:   target -> source
  - Polymorphic realization edges (source=Concrete --[Implements]--> target=Abstract):
      Runtime dispatch flows from Abstract -> Concrete, so:
      downstream: Abstract (kind in POLYMORPHIC_KINDS) -> Concrete (relation='VirtualDispatch')
      upstream:   Concrete -> Abstract (relation='VirtualDispatch')
  This makes upstream and downstream exact inverses while preventing sibling
  implementations from leaking into each other through a shared interface.
"""
from typing import Dict, List, Set, Tuple, Any, Optional

POLYMORPHIC_KINDS = frozenset({"Trait", "Interface", "AbstractMethod", "Protocol"})
IMPLEMENTS_RELATION = "Implements"
VIRTUAL_DISPATCH_RELATION = "VirtualDispatch"
VIRTUAL_DISPATCH_WEIGHT = 0.6


def is_polymorphic_kind(kind: Optional[str]) -> bool:
    """Returns True if a symbol kind represents an abstract polymorphic dispatch target."""
    return bool(kind and kind in POLYMORPHIC_KINDS)


def expand_virtual_neighbors(
    repository,
    symbol: str,
    direction: str,
) -> List[Tuple[str, float, str]]:
    """
    Returns virtual-dispatch neighbor tuples (neighbor_symbol, effective_weight, relation)
    for a single node in either 'upstream' or 'downstream' traversal.
    """
    neighbors: List[Tuple[str, float, str]] = []
    dir_norm = direction.lower()

    if dir_norm in ("upstream", "both"):
        for edge in repository.graph.get_edges(source=symbol, relation=IMPLEMENTS_RELATION):
            weight = float(edge.get("weight", 1.0)) * VIRTUAL_DISPATCH_WEIGHT
            neighbors.append((edge["target"], weight, VIRTUAL_DISPATCH_RELATION))

    if dir_norm in ("downstream", "both"):
        sym_rec = repository.graph.get_symbol(symbol)
        if sym_rec and is_polymorphic_kind(sym_rec.get("kind")):
            for edge in repository.graph.get_edges(target=symbol, relation=IMPLEMENTS_RELATION):
                weight = float(edge.get("weight", 1.0)) * VIRTUAL_DISPATCH_WEIGHT
                neighbors.append((edge["source"], weight, VIRTUAL_DISPATCH_RELATION))

    return neighbors


def build_propagation_adjacency(
    all_edges: List[Dict[str, Any]],
    symbol_classifications: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """
    Builds symmetrical (adj_forward, adj_backward) adjacency maps for MetadataPropagator.
    Standard edges flow source -> target; Implements edges (Concrete -> Abstract) map
    runtime dispatch Abstract -> Concrete so upstream/downstream propagation crosses
    traits and interfaces without leaking across sibling implementations.
    """
    adj_forward: Dict[str, Set[str]] = {}
    adj_backward: Dict[str, Set[str]] = {}

    for edge in all_edges:
        src = edge["source"]
        tgt = edge["target"]
        if src not in symbol_classifications or tgt not in symbol_classifications:
            continue

        if edge.get("relation") == IMPLEMENTS_RELATION:
            # src=Concrete implements tgt=Abstract -> runtime dispatch flows tgt -> src
            tgt_kind = symbol_classifications[tgt].get("symbol_info", {}).get("kind")
            if is_polymorphic_kind(tgt_kind) or tgt_kind in (None, "", "UnspecifiedKind"):
                adj_forward.setdefault(tgt, set()).add(src)
                adj_backward.setdefault(src, set()).add(tgt)
        else:
            adj_forward.setdefault(src, set()).add(tgt)
            adj_backward.setdefault(tgt, set()).add(src)

    return adj_forward, adj_backward
