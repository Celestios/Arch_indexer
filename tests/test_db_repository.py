from unittest.mock import MagicMock
from db.repository import Repository
from db.repository_files import FilesRepository
from db.repository_symbols import SymbolsRepository
from db.repository_edges import EdgesRepository
from db.repository_compliance import ComplianceRepository
from db.repository_metrics import MetricsRepository


class TestRepository:
    def test_default_sub_repositories(self):
        mock_conn = MagicMock()
        repo = Repository(mock_conn)
        assert isinstance(repo.files, FilesRepository)
        assert isinstance(repo.symbols, SymbolsRepository)
        assert isinstance(repo.edges, EdgesRepository)
        assert isinstance(repo.compliance, ComplianceRepository)
        assert isinstance(repo.metrics, MetricsRepository)

    def test_custom_sub_repositories(self):
        mock_conn = MagicMock()
        mock_files = MagicMock(spec=FilesRepository)
        mock_symbols = MagicMock(spec=SymbolsRepository)
        mock_edges = MagicMock(spec=EdgesRepository)
        mock_compliance = MagicMock(spec=ComplianceRepository)
        mock_metrics = MagicMock(spec=MetricsRepository)
        repo = Repository(
            mock_conn,
            files=mock_files,
            symbols=mock_symbols,
            edges=mock_edges,
            compliance=mock_compliance,
            metrics=mock_metrics,
        )
        assert repo.files is mock_files
        assert repo.symbols is mock_symbols
        assert repo.edges is mock_edges
        assert repo.compliance is mock_compliance
        assert repo.metrics is mock_metrics

    def test_stores_db_conn(self):
        mock_conn = MagicMock()
        repo = Repository(mock_conn)
        assert repo.db_conn is mock_conn

    def test_partial_custom_repositories(self):
        mock_conn = MagicMock()
        mock_files = MagicMock(spec=FilesRepository)
        repo = Repository(mock_conn, files=mock_files)
        assert repo.files is mock_files
        assert isinstance(repo.symbols, SymbolsRepository)
        assert isinstance(repo.edges, EdgesRepository)
        assert isinstance(repo.compliance, ComplianceRepository)
        assert isinstance(repo.metrics, MetricsRepository)
