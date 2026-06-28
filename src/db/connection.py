import os
import sys
import duckdb
from pathlib import Path
from contextlib import contextmanager

# Default database file path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / ".arch" / "arch.db"

class DbConnection:
    """
    Manages DuckDB database connections and initialization.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._initialized = False
        self._conn = None

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """
        Creates and returns a connection to the DuckDB database.
        Ensures directories exist. Caches the connection for reuse.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self._conn is None:
            self._conn = duckdb.connect(str(self.db_path))
            
            # Ensure schema is applied
            if not self._initialized:
                self._initialize_schema(self._conn)
                self._initialized = True
            
        return self._conn

    @contextmanager
    def session(self):
        """
        Context manager for handling a connection session.
        Yields the cached connection without closing it, enabling fast query reuse.
        """
        conn = self.get_connection()
        try:
            yield conn
        finally:
            pass

    def close(self):
        """Closes the cached connection if open."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _initialize_schema(self, conn: duckdb.DuckDBPyConnection):
        """Reads schema.sql and applies it to the database connection."""
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            print(f"Warning: schema.sql not found at {schema_path}", file=sys.stderr)
            return

        try:
            schema_sql = schema_path.read_text(encoding="utf-8")
            # DuckDB allows executing multiple SQL statements separated by semicolons
            # We can execute the whole schema string
            conn.execute(schema_sql)
        except Exception as e:
            print(f"Error initializing DuckDB schema: {e}", file=sys.stderr)
            raise e
