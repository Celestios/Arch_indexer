import duckdb
from pathlib import Path
from db.connection import DbConnection


class TestDbConnection:
    def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        try:
            c = conn.get_connection()
            assert db_path.exists()
            assert isinstance(c, duckdb.DuckDBPyConnection)
        finally:
            conn.close()

    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "test.db"
        conn = DbConnection(db_path)
        try:
            conn.get_connection()
            assert db_path.parent.exists()
        finally:
            conn.close()

    def test_connection_is_cached(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        try:
            c1 = conn.get_connection()
            c2 = conn.get_connection()
            assert c1 is c2
        finally:
            conn.close()

    def test_session_yields_connection(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        try:
            with conn.session() as session:
                assert isinstance(session, duckdb.DuckDBPyConnection)
        finally:
            conn.close()

    def test_close_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        conn.get_connection()
        conn.close()
        conn.close()

    def test_reconnect_after_close(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        conn.get_connection()
        conn.close()
        c = conn.get_connection()
        assert isinstance(c, duckdb.DuckDBPyConnection)
        conn.close()

    def test_schema_initialized(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        try:
            c = conn.get_connection()
            tables = c.execute("SHOW TABLES").fetchall()
            assert len(tables) > 0
        finally:
            conn.close()

    def test_schema_not_reapplied_on_reuse(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = DbConnection(db_path)
        try:
            c1 = conn.get_connection()
            c2 = conn.get_connection()
            assert conn._initialized is True
        finally:
            conn.close()

    def test_in_memory_database(self):
        conn = DbConnection(Path(":memory:"))
        try:
            c = conn.get_connection()
            result = c.execute("SELECT 1").fetchone()
            assert result[0] == 1
        finally:
            conn.close()

    def test_custom_db_path(self, tmp_path):
        db_path = tmp_path / "custom_name.db"
        conn = DbConnection(db_path)
        try:
            conn.get_connection()
            assert db_path.exists()
        finally:
            conn.close()

    def test_transaction_commit(self, tmp_path):
        import pytest
        db_path = tmp_path / "tx_commit.db"
        conn = DbConnection(db_path)
        try:
            with conn.transaction() as c:
                c.execute("INSERT INTO system_metadata (key, value) VALUES ('k1', 'v1')")
            val = conn.get_connection().execute("SELECT value FROM system_metadata WHERE key = 'k1'").fetchone()[0]
            assert val == "v1"
        finally:
            conn.close()

    def test_transaction_rollback(self, tmp_path):
        import pytest
        db_path = tmp_path / "tx_rollback.db"
        conn = DbConnection(db_path)
        try:
            with pytest.raises(RuntimeError):
                with conn.transaction() as c:
                    c.execute("INSERT INTO system_metadata (key, value) VALUES ('k2', 'v2')")
                    raise RuntimeError("Forced abort")
            row = conn.get_connection().execute("SELECT value FROM system_metadata WHERE key = 'k2'").fetchone()
            assert row is None
        finally:
            conn.close()
