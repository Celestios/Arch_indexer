from db.connection import DbConnection
from db.repository_files import FilesRepository
from db.repository_symbols import SymbolsRepository
from db.repository_edges import EdgesRepository
from db.repository_compliance import ComplianceRepository
from db.repository_metrics import MetricsRepository


class Repository:
    """
    Composition-based Repository class that delegates tasks to specialized sub-repositories.
    Adheres strictly to SOLID Single Responsibility and Interface Segregation principles.
    """
    def __init__(self, db_conn: DbConnection,
                 files=None, symbols=None, edges=None, compliance=None, metrics=None):
        self.db_conn = db_conn
        self.files = files or FilesRepository(db_conn)
        self.symbols = symbols or SymbolsRepository(db_conn)
        self.edges = edges or EdgesRepository(db_conn)
        self.compliance = compliance or ComplianceRepository(db_conn)
        self.metrics = metrics or MetricsRepository(db_conn)
