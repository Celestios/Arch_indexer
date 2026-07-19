from dataclasses import dataclass
from typing import List, Optional

from .graph_utils import bfs_shortest_path


@dataclass
class FlowStep:
    symbol: str
    filepath: str
    line: int
    col: int
    type_name: Optional[str] = None
    language: Optional[str] = None


class BaseDataflowTracer:
    """Shared base for dataflow tracers. Eliminates duplicated _resolve_locations and _find_path."""

    def __init__(self, repository=None, analyzer_db=None):
        self.repository = repository
        self.analyzer_db = analyzer_db

    def _find_path(self, source: str, sink: str, call_graph: dict) -> List[str]:
        return bfs_shortest_path(source, sink, call_graph)

    def _resolve_locations(self, path: List[str], language: Optional[str] = None) -> List[FlowStep]:
        """Convert symbol IDs to FlowStep with file/line from appropriate databases."""
        steps = []
        for symbol_id in path:
            if self.analyzer_db:
                resolved = self.analyzer_db.get_resolved_symbol(symbol_id)
                if resolved:
                    steps.append(FlowStep(
                        symbol=symbol_id,
                        filepath=resolved['filepath'],
                        line=resolved['line'],
                        col=resolved['col'],
                        type_name=resolved.get('type_name'),
                        language=language
                    ))
                    continue

            if self.repository:
                symbol_info = self.repository.symbols.get_symbol(symbol_id)
                if symbol_info:
                    occs = self.repository.symbols.get_occurrences_for_symbol(symbol_id)
                    if occs:
                        def_occ = next((o for o in occs if o['role'] == 1), occs[0])
                        steps.append(FlowStep(
                            symbol=symbol_id,
                            filepath=def_occ['filepath'],
                            line=def_occ['start_line'],
                            col=def_occ['start_col'],
                            language=language
                        ))
                        continue

        return steps
