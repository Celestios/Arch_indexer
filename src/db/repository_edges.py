from typing import Dict, List, Any, Optional, Tuple
from db.connection import DbConnection


class EdgesRepository:
    """
    Handles queries and updates to the 'edges' table.
    """
    def __init__(self, db_conn: DbConnection):
        self.db_conn = db_conn

    def _query(self, sql: str, params: Optional[Tuple] = None) -> List[Any]:
        """Execute a read query and return all rows."""
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ()).fetchall()

    def _execute(self, sql: str, params: Optional[Tuple] = None) -> Any:
        """Execute a write query and return the result."""
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ())

    def add_edge(self, source: str, target: str, relation: str, weight: float = 1.0):
        """Registers a structural call or dependency link between two symbols."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO edges (source, target, relation, weight)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (source, target, relation, weight)
            )

    def get_outgoing_edges(self, symbol: str) -> List[Dict[str, str]]:
        """Lists all symbols directly referenced/called by the given symbol."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT target, relation FROM edges WHERE source = ?",
                (symbol,)
            ).fetchall()
            return [{"target": r[0], "relation": r[1]} for r in res]

    def get_incoming_edges(self, symbol: str) -> List[Dict[str, str]]:
        """Lists all callers/parents referencing the given symbol (backreferences)."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT source, relation FROM edges WHERE target = ?",
                (symbol,)
            ).fetchall()
            return [{"source": r[0], "relation": r[1]} for r in res]

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
                """
                INSERT INTO edges (source, target, relation, weight)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
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

    def get_transitive_closure(self, symbol: str, max_depth: int = 3) -> Dict[str, List[Dict[str, Any]]]:
        """
        Computes the transitive closure of callers (upstream) and callees (downstream)
        for a given symbol up to max_depth.
        Returns a dict: {"upstream": [...], "downstream": [...]}
        """
        upstream = []
        downstream = []

        with self.db_conn.session() as conn:
            # Upstream BFS (incoming callers)
            queue = [(symbol, 0, [symbol])]
            visited = {symbol}
            while queue:
                curr, depth, path = queue.pop(0)
                if depth >= max_depth:
                    continue
                callers = conn.execute(
                    "SELECT source FROM edges WHERE target = ?", (curr,)
                ).fetchall()
                for (caller,) in callers:
                    if caller not in visited:
                        visited.add(caller)
                        new_path = [caller] + path
                        upstream.append({
                            "symbol": caller,
                            "depth": depth + 1,
                            "path": new_path
                        })
                        queue.append((caller, depth + 1, new_path))

            # Downstream BFS (outgoing callees)
            queue = [(symbol, 0, [symbol])]
            visited = {symbol}
            while queue:
                curr, depth, path = queue.pop(0)
                if depth >= max_depth:
                    continue
                callees = conn.execute(
                    "SELECT target FROM edges WHERE source = ?", (curr,)
                ).fetchall()
                for (callee,) in callees:
                    if callee not in visited:
                        visited.add(callee)
                        new_path = path + [callee]
                        downstream.append({
                            "symbol": callee,
                            "depth": depth + 1,
                            "path": new_path
                        })
                        queue.append((callee, depth + 1, new_path))

        return {"upstream": upstream, "downstream": downstream}

    def get_all_edges(self):
        """Returns all edges with source, target, weight. Used by communities.py and auditor."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT source, target, weight FROM edges"
            ).fetchall()
            return [{"source": r[0], "target": r[1], "weight": r[2]} for r in res]

    def get_all_edges_with_relation(self):
        """Returns all edges with source, target, relation. Used by auditor."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT source, target, relation FROM edges"
            ).fetchall()
            return [{"source": r[0], "target": r[1], "relation": r[2]} for r in res]

    def update_edge_weights_bulk(self, weight_updates):
        """Bulk update edge weights in a single transaction.
        
        Args:
            weight_updates: List of (weight, source, target, relation) tuples
        """
        if not weight_updates:
            return
        with self.db_conn.session() as conn:
            conn.executemany(
                "UPDATE edges SET weight = ? WHERE source = ? AND target = ? AND relation = ?",
                weight_updates
            )
