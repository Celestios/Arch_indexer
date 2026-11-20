"""Immutable snapshot of the architectural index used during a single audit pass.

The snapshot performs the bulk database reads once and exposes pure accessors for
the hot paths (symbol/definition/incoming-edge lookups) so the audit and the
violation checkers operate completely in-memory with zero per-node database queries.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from db.repository import Repository


@dataclass(frozen=True)
class AuditSnapshot:
    """Bulk-loaded, pure immutable view of files, symbols, edges and definitions."""

    all_files: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    all_symbols: List[Dict[str, Any]] = field(default_factory=list)
    all_edges: List[Dict[str, Any]] = field(default_factory=list)
    symbol_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    outgoing_map: Dict[str, List[str]] = field(default_factory=dict)
    incoming_map: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    definitions_by_symbol: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        repository: "Repository",
        symbols: Optional[List[Dict[str, Any]]] = None,
        edges: Optional[List[Dict[str, Any]]] = None,
        files: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> "AuditSnapshot":
        """Loads (or reuses caller-supplied) bulk data for one audit pass."""
        if symbols is None:
            symbols = repository.graph.get_all_symbols()
        if edges is None:
            edges = repository.graph.get_all_edges()
        if files is None:
            files = repository.workspace.get_all_files_metadata()

        symbol_map: Dict[str, Dict[str, Any]] = {}
        for sym in symbols:
            if "symbol" in sym:
                symbol_map[sym["symbol"]] = sym

        outgoing_map: Dict[str, List[str]] = {}
        incoming_map: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            src = edge.get("source")
            tgt = edge.get("target")
            if src and tgt:
                outgoing_map.setdefault(src, []).append(tgt)
            if tgt:
                incoming_map.setdefault(tgt, []).append({
                    "source": src,
                    "relation": edge.get("relation"),
                    "weight": edge.get("weight", 1.0),
                    "call_line": edge.get("call_line"),
                })

        definitions_by_symbol = repository.graph.get_definitions_map()

        return cls(
            all_files=files,
            all_symbols=symbols,
            all_edges=edges,
            symbol_map=symbol_map,
            outgoing_map=outgoing_map,
            incoming_map=incoming_map,
            definitions_by_symbol=definitions_by_symbol,
        )

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns symbol metadata from the snapshot."""
        return self.symbol_map.get(symbol)

    def get_definition(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns definition metadata (filepath, start_line, etc.) for a symbol."""
        return self.definitions_by_symbol.get(symbol)

    def get_incoming(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns incoming edges (with source/relation/weight/call_line) for a symbol."""
        return self.incoming_map.get(symbol, [])

    def get_outgoing(self, symbol: str) -> List[str]:
        """Returns outgoing callee symbol identifiers."""
        return self.outgoing_map.get(symbol, [])
