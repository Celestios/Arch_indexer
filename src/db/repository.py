from typing import List, Optional
from db.connection import DbConnection
from db.base import normalize_path
from db.store_workspace import WorkspaceStore
from db.store_graph import GraphStore
from db.store_quality import QualityStore
from db.store_analytics import AnalyticsStore


class Repository:
    """Unified repository facade over the 4 symmetrical domain stores."""

    def __init__(
        self,
        db_conn: DbConnection,
        workspace: Optional[WorkspaceStore] = None,
        graph: Optional[GraphStore] = None,
        quality: Optional[QualityStore] = None,
        analytics: Optional[AnalyticsStore] = None,
    ):
        self._db_conn = db_conn
        self.workspace = workspace or WorkspaceStore(db_conn)
        self.graph = graph or GraphStore(db_conn)
        self.quality = quality or QualityStore(db_conn)
        self.analytics = analytics or AnalyticsStore(db_conn)

    def transaction(self):
        """Atomic transaction context manager."""
        return self._db_conn.transaction()

    def delete_files(self, filepaths: List[str]):
        """Atomic cross-domain cascade delete across edges, occurrences, diagnostics, symbols, and files."""
        if not filepaths:
            return
        fps = [normalize_path(fp) for fp in filepaths]
        with self._db_conn.transaction() as conn:
            conn.execute(
                """
                DELETE FROM edges
                WHERE source IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))
                   OR target IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))
                """,
                (fps, fps)
            )
            conn.execute(
                "DELETE FROM occurrences WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                (fps,)
            )
            conn.execute(
                "DELETE FROM diagnostics WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                (fps,)
            )
            conn.execute(
                "DELETE FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                (fps,)
            )
            conn.execute(
                "DELETE FROM files WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                (fps,)
            )

    def delete_file(self, filepath: str):
        """Atomic cross-domain cascade delete for a single file."""
        self.delete_files([filepath])
