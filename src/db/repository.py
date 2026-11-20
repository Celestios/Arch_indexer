from typing import List, Optional
from db.connection import DbConnection
from db.store_workspace import WorkspaceStore
from db.store_graph import GraphStore
from db.store_quality import QualityStore
from db.store_analytics import AnalyticsStore

from db.repository_files import FilesRepository
from db.repository_symbols import SymbolsRepository
from db.repository_edges import EdgesRepository
from db.repository_compliance import ComplianceRepository
from db.repository_metrics import MetricsRepository
from db.repository_occurrences import OccurrencesRepository
from db.repository_diagnostics import DiagnosticsRepository
from db.repository_metadata import MetadataRepository
from db.repository_coupling import CouplingRepository
from db.cascade import CascadeCleanupService


class Repository:
    """
    Facade providing access to the 4 symmetrical domain stores:
    - workspace: WorkspaceStore (files, system_metadata, file_co_changes)
    - graph: GraphStore (symbols, edges, occurrences, atomic cascade deletions)
    - quality: QualityStore (compliance_rules, compliance_violations, diagnostics)
    - analytics: AnalyticsStore (metrics, transitive closures, graph snapshot data)

    Maintains 100% backward-compatible sub-repository delegates for legacy callers and tests.
    """

    def __init__(
        self,
        db_conn: DbConnection,
        files=None,
        symbols=None,
        edges=None,
        compliance=None,
        metrics=None,
        occurrences=None,
        diagnostics=None,
        metadata=None,
        coupling=None,
        workspace=None,
        graph=None,
        quality=None,
        analytics=None,
    ):
        self._db_conn = db_conn
        self.db_conn = db_conn

        self.workspace = workspace or WorkspaceStore(db_conn)
        self.graph = graph or GraphStore(db_conn)
        self.quality = quality or QualityStore(db_conn)
        self.analytics = analytics or AnalyticsStore(db_conn)

        # Backward compatibility delegates
        self.files = files or FilesRepository(db_conn)
        self.edges = edges or EdgesRepository(db_conn)
        self.compliance = compliance or ComplianceRepository(db_conn)
        self.metrics = metrics or MetricsRepository(db_conn)
        self.occurrences = occurrences or OccurrencesRepository(db_conn)
        self.diagnostics = diagnostics or DiagnosticsRepository(db_conn)
        self.metadata = metadata or MetadataRepository(db_conn)
        self.coupling = coupling or CouplingRepository(db_conn)

        if symbols:
            self.symbols = symbols
        else:
            self.symbols = SymbolsRepository(
                db_conn,
                occurrences=self.occurrences,
                diagnostics=self.diagnostics,
                edges=self.edges,
            )

        self.cascade = CascadeCleanupService(self)

    def delete_file(self, filepath: str):
        """Cross-table cascade delete of a file and its associated data."""
        self.graph.delete_files([filepath])

    def delete_files_bulk(self, filepaths: List[str]):
        """Cross-table cascade delete of multiple files and their associated data."""
        self.graph.delete_files(filepaths)

    def clean_files_symbols_and_relations(self, filepaths: List[str]):
        """Alias for delete_files_bulk."""
        self.graph.delete_files(filepaths)
