from typing import Dict, Any, List, Optional, Tuple
from db.connection import DbConnection


class MetricsRepository:
    """
    Handles queries for codebase metrics, statistics, and counts.
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

    def get_symbol_counts_by_kind(self) -> Dict[str, int]:
        """Returns symbol counts grouped by their declaration kind."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT kind, COUNT(*) FROM symbols GROUP BY kind"
            ).fetchall()
            return {r[0]: r[1] for r in res}

    def get_repo_totals(self) -> Dict[str, int]:
        """Returns total counts for files, symbols, edges, and violations."""
        with self.db_conn.session() as conn:
            files_cnt = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            symbols_cnt = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            edges_cnt = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            violations_cnt = conn.execute("SELECT COUNT(*) FROM compliance_violations").fetchone()[0]
            return {
                "files": files_cnt,
                "symbols": symbols_cnt,
                "edges": edges_cnt,
                "violations": violations_cnt
            }

    def get_symbols_by_file_prefix(self) -> Dict[str, int]:
        """Groups symbol counts by their top-level directory prefix."""
        prefix_counts = {}
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath FROM symbols WHERE filepath IS NOT NULL"
            ).fetchall()
            for (fp,) in res:
                fp_norm = fp.replace("\\", "/")
                parts = fp_norm.split("/")
                if len(parts) > 1:
                    if len(parts) >= 3:
                        prefix = f"{parts[0]}/{parts[1]}/"
                    else:
                        prefix = f"{parts[0]}/"
                else:
                    prefix = "./"
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        return prefix_counts
