from unittest.mock import MagicMock
from db.repository import Repository
from db.store_workspace import WorkspaceStore
from db.store_graph import GraphStore
from db.store_quality import QualityStore
from db.store_analytics import AnalyticsStore


class TestRepository:
    def test_default_domain_stores(self):
        mock_conn = MagicMock()
        repo = Repository(mock_conn)
        assert isinstance(repo.workspace, WorkspaceStore)
        assert isinstance(repo.graph, GraphStore)
        assert isinstance(repo.quality, QualityStore)
        assert isinstance(repo.analytics, AnalyticsStore)

    def test_custom_domain_stores(self):
        mock_conn = MagicMock()
        mock_ws = MagicMock(spec=WorkspaceStore)
        mock_graph = MagicMock(spec=GraphStore)
        mock_quality = MagicMock(spec=QualityStore)
        mock_analytics = MagicMock(spec=AnalyticsStore)
        repo = Repository(
            mock_conn,
            workspace=mock_ws,
            graph=mock_graph,
            quality=mock_quality,
            analytics=mock_analytics,
        )
        assert repo.workspace is mock_ws
        assert repo.graph is mock_graph
        assert repo.quality is mock_quality
        assert repo.analytics is mock_analytics

    def test_stores_db_conn(self):
        mock_conn = MagicMock()
        repo = Repository(mock_conn)
        assert repo.db_conn is mock_conn

    def test_domain_stores_integration(self, tmp_path):
        from db.connection import DbConnection
        db_path = tmp_path / "test_domain.db"
        conn = DbConnection(db_path)
        try:
            repo = Repository(conn)

            # WorkspaceStore
            repo.workspace.upsert_file("src\\main.py", "hash123", "python")
            f = repo.workspace.get_file("src/main.py")
            assert f is not None
            assert f["filepath"] == "src/main.py"
            assert f["language"] == "python"

            repo.workspace.set_metadata("version", "1.0.0")
            assert repo.workspace.get_metadata("version") == "1.0.0"

            repo.workspace.record_co_changes([("src/a.py", "src/b.py", 5, 0.8)])
            co = repo.workspace.get_co_changes("src/a.py")
            assert len(co) == 1
            assert co[0]["co_change_count"] == 5

            # GraphStore
            repo.graph.upsert_symbol(
                symbol="my_func",
                filepath="src/main.py",
                kind="Function",
                signature="def my_func(): pass",
                start_line=10,
                start_col=1,
                end_line=12,
                end_col=5,
            )
            s = repo.graph.get_symbol("my_func")
            assert s is not None
            assert s["start_line"] == 10

            repo.graph.add_edge("my_func", "dep_func", "Calls", 1.5, call_line=11)
            edges = repo.graph.get_edges(source="my_func")
            assert len(edges) == 1
            assert edges[0]["call_line"] == 11

            repo.graph.record_occurrences_bulk([{
                "symbol": "my_func",
                "filepath": "src/main.py",
                "start_line": 10,
                "start_col": 1,
                "end_line": 12,
                "end_col": 5,
                "role": 1,
            }])
            occs = repo.graph.get_occurrences_for_symbol("my_func")
            assert len(occs) == 1

            # QualityStore
            repo.quality.upsert_rule("ARCH001", "Rule 1", "Error")
            rules = repo.quality.get_rules()
            assert any(r["rule_id"] == "ARCH001" for r in rules)

            repo.quality.record_violations_bulk([{
                "violation_id": "v1",
                "rule_id": "ARCH001",
                "symbol": "my_func",
                "filepath": "src/main.py",
                "line": 10,
                "message": "Violation 1",
            }])
            viols = repo.quality.get_violations(filepath="src/main.py")
            assert len(viols) == 1

            # AnalyticsStore
            metrics = repo.analytics.get_symbol_metrics()
            assert metrics["totals"]["symbols"] == 1
            closure = repo.analytics.get_transitive_closure("my_func")
            assert len(closure["downstream"]) == 1
            assert closure["downstream"][0]["symbol"] == "dep_func"

            # Atomic cascade delete
            repo.delete_file("src/main.py")
            assert repo.workspace.get_file("src/main.py") is None
            assert repo.graph.get_symbol("my_func") is None
            assert len(repo.graph.get_edges(source="my_func")) == 0
            assert len(repo.graph.get_occurrences_for_symbol("my_func")) == 0
        finally:
            conn.close()
