from collections import deque
from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository


class EdgesRepository(BaseRepository):
    """Handles queries and updates to the 'edges' table."""

    def add_edge(self, source: str, target: str, relation: str, weight: float = 1.0):
        """Registers a structural call or dependency link between two symbols."""
        with self.db_conn.session() as conn:
            conn.execute(
                "INSERT INTO edges (source, target, relation, weight) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (source, target, relation, weight)
            )

    def get_outgoing_edges(self, symbol: str) -> List[Dict[str, Any]]:
        """Lists all symbols directly referenced/called by the given symbol."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT target, relation, weight FROM edges WHERE source = ?",
                (symbol,)
            ).fetchall()
            return [{"target": r[0], "relation": r[1], "weight": r[2] if len(r) > 2 else 1.0} for r in res]

    def get_incoming_edges(self, symbol: str) -> List[Dict[str, Any]]:
        """Lists all callers/parents referencing the given symbol."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT source, relation, weight FROM edges WHERE target = ?",
                (symbol,)
            ).fetchall()
            return [{"source": r[0], "relation": r[1], "weight": r[2] if len(r) > 2 else 1.0} for r in res]

    def add_edges_bulk(self, edges_list: List[Dict[str, Any]]):
        """Bulk inserts a list of edges in a single transaction."""
        if not edges_list:
            return
        data = [
            (
                edge["source"],
                edge["target"],
                edge["relation"],
                edge.get("weight", 1.0)
            )
            for edge in edges_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                "INSERT INTO edges (source, target, relation, weight) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                data
            )

    def delete_edges_for_file(self, filepath: str):
        """Delete all edges linking to symbols in a specific file."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                DELETE FROM edges
                WHERE source IN (SELECT symbol FROM symbols WHERE filepath = ?)
                   OR target IN (SELECT symbol FROM symbols WHERE filepath = ?)
                """,
                (filepath, filepath)
            )

    def delete_edges_for_files(self, filepaths: List[str]):
        """Delete all edges linking to symbols in multiple files."""
        if not filepaths:
            return
        with self.db_conn.session() as conn:
            conn.execute(
                """
                DELETE FROM edges
                WHERE source IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))
                   OR target IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))
                """,
                (filepaths, filepaths)
            )

    def delete_orphaned_edges(self) -> int:
        """Delete edges where source or target symbol no longer exists in the symbols table.
        Returns the number of orphaned edges deleted."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                DELETE FROM edges
                WHERE source NOT IN (SELECT symbol FROM symbols)
                   OR target NOT IN (SELECT symbol FROM symbols)
                """
            )
            return res.rowcount if res.rowcount else 0

    def get_transitive_closure(self, symbol: str, max_depth: int = 3) -> Dict[str, List[Dict[str, Any]]]:
        """Computes the transitive closure of callers (upstream) and callees (downstream)."""
        upstream = []
        downstream = []
        with self.db_conn.session() as conn:
            # Upstream BFS (callers)
            visited = {symbol}
            current_frontier = {symbol: [symbol]}
            for depth in range(max_depth):
                if not current_frontier:
                    break
                nodes = list(current_frontier.keys())
                rows = conn.execute(
                    "SELECT source, target, relation FROM edges WHERE target IN (SELECT UNNEST(?::VARCHAR[]))",
                    (nodes,)
                ).fetchall()
                next_frontier = {}
                for caller, tgt, rel in rows:
                    if caller not in visited:
                        visited.add(caller)
                        new_path = [caller] + current_frontier[tgt]
                        upstream.append({"symbol": caller, "depth": depth + 1, "path": new_path, "relation": rel})
                        next_frontier[caller] = new_path
                current_frontier = next_frontier

            # Downstream BFS (callees)
            visited = {symbol}
            current_frontier = {symbol: [symbol]}
            for depth in range(max_depth):
                if not current_frontier:
                    break
                nodes = list(current_frontier.keys())
                rows = conn.execute(
                    "SELECT target, source, relation FROM edges WHERE source IN (SELECT UNNEST(?::VARCHAR[]))",
                    (nodes,)
                ).fetchall()
                next_frontier = {}
                for callee, src, rel in rows:
                    if callee not in visited:
                        visited.add(callee)
                        new_path = current_frontier[src] + [callee]
                        downstream.append({"symbol": callee, "depth": depth + 1, "path": new_path, "relation": rel})
                        next_frontier[callee] = new_path
                current_frontier = next_frontier

        return {"upstream": upstream, "downstream": downstream}

    def get_all_edges(self):
        """Returns all edges with source, target, weight."""
        with self.db_conn.session() as conn:
            res = conn.execute("SELECT source, target, weight FROM edges").fetchall()
            return [{"source": r[0], "target": r[1], "weight": r[2]} for r in res]

    def get_all_edges_with_relation(self):
        """Returns all edges with source, target, relation."""
        with self.db_conn.session() as conn:
            res = conn.execute("SELECT source, target, relation FROM edges").fetchall()
            return [{"source": r[0], "target": r[1], "relation": r[2]} for r in res]

    def update_edge_weights_bulk(self, weight_updates):
        """Bulk update edge weights in a single transaction."""
        if not weight_updates:
            return
        with self.db_conn.session() as conn:
            conn.executemany(
                "UPDATE edges SET weight = ? WHERE source = ? AND target = ? AND relation = ?",
                weight_updates
            )

    def get_dependent_files(self, filepaths: List[str]) -> List[str]:
        """Find all files that call symbols defined in the given files using a single join query."""
        if not filepaths:
            return []
        with self.db_conn.session() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT s_caller.filepath
                FROM symbols s_def
                JOIN edges e ON e.target = s_def.symbol
                JOIN symbols s_caller ON e.source = s_caller.symbol
                WHERE s_def.filepath IN (SELECT UNNEST(?::VARCHAR[]))
                  AND s_caller.filepath IS NOT NULL
                """,
                (filepaths,)
            ).fetchall()
            return [r[0] for r in rows if r[0]]
