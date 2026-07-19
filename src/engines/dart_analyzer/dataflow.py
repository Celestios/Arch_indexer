from typing import List
from pathlib import Path

from .base_tracer import BaseDataflowTracer, FlowStep


class DartDataflowTracer(BaseDataflowTracer):
    """
    Traces data flow between two symbols using Dart analyzer.
    Queries both dart_analyzer_db and arch.db (SCIP) for complete picture.
    """

    def __init__(self, project_root: Path, analyzer_db, repository):
        super().__init__(repository=repository, analyzer_db=analyzer_db)
        self.project_root = project_root

    def trace(self, source_symbol: str, sink_symbol: str) -> List[FlowStep]:
        """Find data flow path from source to sink."""
        cached_path = self.analyzer_db.get_dataflow_path(source_symbol, sink_symbol)
        if cached_path:
            return self._resolve_locations(cached_path)

        call_graph = self._build_combined_call_graph()
        path = self._find_path(source_symbol, sink_symbol, call_graph)

        if path:
            self.analyzer_db.cache_dataflow_path(source_symbol, sink_symbol, path, len(path))

        return self._resolve_locations(path)

    def _build_combined_call_graph(self) -> dict:
        """Merge edges from analyzer DB typed_edges and SCIP edges."""
        graph = {}

        with self.analyzer_db.session() as conn:
            rows = conn.execute("SELECT source_id, target_id FROM typed_edges").fetchall()
            for row in rows:
                graph.setdefault(row['source_id'], []).append(row['target_id'])

        if self.repository:
            with self.repository.db_conn.session() as conn:
                rows = conn.execute(
                    "SELECT source, target FROM edges WHERE relation IN ('Calls', 'FFI_Binds')"
                ).fetchall()
                for row in rows:
                    graph.setdefault(row[0], []).append(row[1])

        return graph
