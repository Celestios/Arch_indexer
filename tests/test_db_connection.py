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
