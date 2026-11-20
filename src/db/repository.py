from typing import List, Optional
from db.connection import DbConnection
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
    Composition-based Repository class that delegates tasks to specialized sub-repositories.
    Adheres strictly to SOLID Single Responsibility and Interface Segregation principles.
    """
    def __init__(self, db_conn: DbConnection,
                 files=None, symbols=None, edges=None, compliance=None, metrics=None,
                 occurrences=None, diagnostics=None, metadata=None, coupling=None):
        self.db_conn = db_conn
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
                edges=self.edges
            )

        self.cascade = CascadeCleanupService(self)

    def delete_file(self, filepath: str):
        """Cross-table cascade delete of a file and its associated data."""
        self.cascade.delete_file(filepath)

    def delete_files_bulk(self, filepaths: List[str]):
        """Cross-table cascade delete of multiple files and their associated data."""
        self.cascade.delete_files_bulk(filepaths)

    def clean_files_symbols_and_relations(self, filepaths: List[str]):
        """Alias for delete_files_bulk."""
        self.cascade.delete_files_bulk(filepaths)
