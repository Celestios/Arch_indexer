from typing import List, Optional
from db.connection import DbConnection
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

    @property
    def db_conn(self) -> DbConnection:
        return self._db_conn

    def delete_file(self, filepath: str):
        """Cross-table cascade delete of a file and its associated data."""
        self.graph.delete_file(filepath)
        self.workspace.delete_file_record(filepath)

    def delete_files_bulk(self, filepaths: List[str]):
        """Cross-table cascade delete of multiple files and their associated data."""
        self.graph.delete_files_bulk(filepaths)
        self.workspace.delete_files_records(filepaths)
