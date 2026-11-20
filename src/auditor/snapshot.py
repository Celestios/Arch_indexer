"""Immutable snapshot of the architectural index used during a single audit pass.

The snapshot performs the bulk database reads once and exposes cheap accessors for
the hot paths (symbol/occurrence/incoming-edge lookups) so the audit and the
violation checkers no longer issue redundant per-node queries.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from db.repository import Repository


@dataclass(frozen=True)
class AuditSnapshot:
    """Bulk-loaded view of files, symbols, edges and definitions."""

    repository: "Repository" = field(repr=False, compare=False)
    all_files: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    all_symbols: List[Dict[str, Any]] = field(default_factory=list)
    all_edges: List[Dict[str, Any]] = field(default_factory=list)
    symbol_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    outgoing_map: Dict[str, List[str]] = field(default_factory=dict)
    incoming_map: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    definitions_by_symbol: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    occurrence_cache: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    symbol_cache: Dict[str, Optional[Dict[str, Any]]] = field(default_factory=dict)

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
            symbols = repository.symbols.get_all_symbols_with_metadata()
        if edges is None:
            edges = repository.edges.get_all_edges_with_relation()
        if files is None:
            files = repository.files.get_all_files_metadata()

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
                })

        definitions_by_symbol = repository.symbols.get_definitions_map()

        return cls(
            repository=repository,
            all_files=files,
            all_symbols=symbols,
            all_edges=edges,
            symbol_map=symbol_map,
            outgoing_map=outgoing_map,
            incoming_map=incoming_map,
            definitions_by_symbol=definitions_by_symbol,
        )

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns symbol metadata from the bulk map, falling back to a cached query."""
        if symbol in self.symbol_map:
            return self.symbol_map[symbol]
        if symbol in self.symbol_cache:
            return self.symbol_cache[symbol]
        record = self.repository.symbols.get_symbol(symbol)
        self.symbol_cache[symbol] = record
        return record

    def get_occurrences(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns occurrences for a symbol, memoizing the repository query."""
        if symbol not in self.occurrence_cache:
            self.occurrence_cache[symbol] = self.repository.symbols.get_occurrences_for_symbol(symbol)
        return self.occurrence_cache[symbol]

    def get_definition(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns definition metadata (filepath, start_line, etc.) for a symbol."""
        return self.definitions_by_symbol.get(symbol)

    def get_incoming(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns incoming edges (with source/relation/weight) for a symbol."""
        return self.incoming_map.get(symbol, [])
