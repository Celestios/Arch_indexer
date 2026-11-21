import logging
from typing import Dict, List, Any
from db.base import BaseRepository, normalize_path

logger = logging.getLogger(__name__)


class AnalyticsStore(BaseRepository):
    """
    Domain store providing read-only analytical queries, graph intelligence summaries,
    transitive closures, and metric aggregations.
    """

    def get_symbol_counts_by_kind(self) -> Dict[str, int]:
        """Returns symbol counts grouped by their declaration kind."""
        rows = self._fetch_all("SELECT kind, COUNT(*) AS cnt FROM symbols GROUP BY kind")
        return {r["kind"]: r["cnt"] for r in rows}

    def get_repo_totals(self) -> Dict[str, int]:
        """Returns total counts for files, symbols, edges, occurrences, and violations."""
        files_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM files") or {}).get("cnt", 0)
        symbols_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM symbols") or {}).get("cnt", 0)
        edges_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM edges") or {}).get("cnt", 0)
        violations_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM compliance_violations") or {}).get("cnt", 0)
        occ_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM occurrences") or {}).get("cnt", 0)
        return {
            "files": files_cnt,
            "symbols": symbols_cnt,
            "edges": edges_cnt,
            "violations": violations_cnt,
            "occurrences": occ_cnt,
        }

    def get_symbols_by_file_prefix(self) -> Dict[str, int]:
        """Groups symbol counts by top-level directory prefix."""
        prefix_counts: Dict[str, int] = {}
        rows = self._fetch_all("SELECT filepath FROM symbols WHERE filepath IS NOT NULL")
        for r in rows:
            fp_norm = normalize_path(r["filepath"])
            if not fp_norm:
                continue
            parts = fp_norm.split("/")
            if len(parts) > 1:
                prefix = f"{parts[0]}/{parts[1]}/" if len(parts) >= 3 else f"{parts[0]}/"
            else:
                prefix = "./"
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        return prefix_counts

    def get_symbol_count_by_languages(self, languages: List[str]) -> int:
        """Returns the count of symbols originating from files of specific languages."""
        if not languages:
            return 0
        row = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM symbols WHERE filepath IN (SELECT filepath FROM files WHERE language IN (SELECT UNNEST(?::VARCHAR[])))",
            (languages,),
        )
        return row["cnt"] if row else 0

    def get_transitive_closure(
        self,
        symbol: str,
        max_depth: int = 4,
        direction: str = "both",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """BFS graph traversal finding upstream (callers) and/or downstream (callees) symbols."""
        upstream: List[Dict[str, Any]] = []
        downstream: List[Dict[str, Any]] = []
        dir_norm = (direction or "both").lower()

        if dir_norm in ("upstream", "both"):
            visited = {symbol}
            current_frontier = {symbol: [symbol]}
            for depth in range(max_depth):
                if not current_frontier:
                    break
                nodes = list(current_frontier.keys())
                rows = self._fetch_all(
                    "SELECT source, target, relation FROM edges WHERE target IN (SELECT UNNEST(?::VARCHAR[]))",
                    (nodes,),
                )
                next_frontier = {}
                for r in rows:
                    caller, tgt, rel = r["source"], r["target"], r["relation"]
                    if caller not in visited:
                        visited.add(caller)
                        new_path = [caller] + current_frontier[tgt]
                        upstream.append({
                            "symbol": caller,
                            "parent": tgt,
                            "depth": depth + 1,
                            "path": new_path,
                            "relation": rel,
                        })
                        next_frontier[caller] = new_path
                current_frontier = next_frontier

        if dir_norm in ("downstream", "both"):
            visited = {symbol}
            current_frontier = {symbol: [symbol]}
            for depth in range(max_depth):
                if not current_frontier:
                    break
                nodes = list(current_frontier.keys())
                rows = self._fetch_all(
                    "SELECT target, source, relation FROM edges WHERE source IN (SELECT UNNEST(?::VARCHAR[]))",
                    (nodes,),
                )
                next_frontier = {}
                for r in rows:
                    callee, src, rel = r["target"], r["source"], r["relation"]
                    if callee not in visited:
                        visited.add(callee)
                        new_path = current_frontier[src] + [callee]
                        downstream.append({
                            "symbol": callee,
                            "parent": src,
                            "depth": depth + 1,
                            "path": new_path,
                            "relation": rel,
                        })
                        next_frontier[callee] = new_path
                current_frontier = next_frontier

        return {"upstream": upstream, "downstream": downstream}

    def get_graph_snapshot_data(self) -> Dict[str, Any]:
        """Consolidates workspace summary stats for graph ingestion."""
        totals = self.get_repo_totals()
        def_row = self._fetch_one("SELECT COUNT(*) AS cnt FROM symbols WHERE start_line IS NOT NULL")
        return {
            "files_count": totals["files"],
            "symbols_count": totals["symbols"],
            "edges_count": totals["edges"],
            "occurrences_count": totals["occurrences"],
            "definitions_count": def_row["cnt"] if def_row else 0,
            "references_count": totals["occurrences"],
        }

