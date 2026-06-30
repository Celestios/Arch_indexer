from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path
from collections import deque

@dataclass
class FlowStep:
    symbol: str
    filepath: str
    line: int
    col: int
    type_name: Optional[str] = None

class DartDataflowTracer:
    """
    Traces data flow between two symbols using Dart analyzer.
    Queries both dart_analyzer_db and arch.db (SCIP) for complete picture.
    """

    def __init__(self, project_root: Path, analyzer_db, repository):
        self.project_root = project_root
        self.analyzer_db = analyzer_db
        self.repository = repository  # DuckDB repository (SCIP data)

    def trace(self, source_symbol: str, sink_symbol: str) -> List[FlowStep]:
        """
        Find data flow path from source to sink.
        Combines analyzer DB typed edges with SCIP edges.
        """
        # 1. Check analyzer DB cache first
        cached_path = self.analyzer_db.get_dataflow_path(source_symbol, sink_symbol)
        if cached_path:
            return self._resolve_locations(cached_path)

        # 2. Build combined call graph from both databases
        call_graph = self._build_combined_call_graph()

        # 3. BFS shortest path
        path = self._find_path(source_symbol, sink_symbol, call_graph)

        if path:
            # 4. Cache result in analyzer DB
            self.analyzer_db.cache_dataflow_path(
                source_symbol, sink_symbol, path, len(path)
            )

        # 5. Resolve locations from both databases
        return self._resolve_locations(path)

    def _build_combined_call_graph(self) -> dict:
        """
        Merge edges from:
        - dart_analyzer_db.typed_edges (type-resolved, Dart-only)
        - arch.db edges (SCIP, cross-language)
        """
        graph = {}

        # 1. Load typed edges from analyzer DB
        with self.analyzer_db.session() as conn:
            rows = conn.execute("SELECT source_id, target_id FROM typed_edges").fetchall()
            for row in rows:
                graph.setdefault(row['source_id'], []).append(row['target_id'])

        # 2. Load SCIP edges (includes cross-language FFI_Binds)
        if self.repository:
            with self.repository.db_conn.session() as conn:
                rows = conn.execute(
                    "SELECT source, target FROM edges WHERE relation IN ('Calls', 'FFI_Binds')"
                ).fetchall()
                for row in rows:
                    graph.setdefault(row[0], []).append(row[1])

        return graph

    def _find_path(self, source: str, sink: str, call_graph: dict) -> List[str]:
        """BFS shortest path in combined call graph."""
        if source not in call_graph and source != sink:
            return []

        visited = {source}
        queue = deque([(source, [source])])

        while queue:
            current, path = queue.popleft()
            if current == sink:
                return path
            for neighbor in call_graph.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []

    def _resolve_locations(self, path: List[str]) -> List[FlowStep]:
        """Convert symbol IDs to FlowStep with file/line from both databases."""
        steps = []
        for symbol_id in path:
            # Try analyzer DB first (type-resolved)
            resolved = self.analyzer_db.get_resolved_symbol(symbol_id)
            if resolved:
                steps.append(FlowStep(
                    symbol=symbol_id,
                    filepath=resolved['filepath'],
                    line=resolved['line'],
                    col=resolved['col'],
                    type_name=resolved['type_name']
                ))
                continue

            # Fallback to SCIP occurrences
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
                            col=def_occ['start_col']
                        ))

        return steps
