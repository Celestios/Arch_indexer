from typing import Dict, List, Any
from db.base import BaseRepository

class EdgesRepository(BaseRepository):
    """
    Handles queries and updates to the 'edges' table.
    """

    def add_edge(self, source: str, target: str, relation: str):
        """Registers a structural call or dependency link between two symbols."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO edges (source, target, relation)
                VALUES (?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (source, target, relation)
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
        data = [
            (
                edge["source"],
                edge["target"],
                edge["relation"]
            )
            for edge in edges_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO edges (source, target, relation)
                VALUES (?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                data
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
