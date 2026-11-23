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
            try:
                self._conn = duckdb.connect(str(self.db_path))
            except Exception as e:
                # Handle known DuckDB WAL replay bug (e.g. "Failure while replaying WAL file")
                wal_path = self.db_path.with_name(self.db_path.name + ".wal")
                if "Failure while replaying WAL file" in str(e) and wal_path.exists():
                    import shutil
                    corrupt_backup = self.db_path.with_name(self.db_path.name + ".wal.corrupt")
                    print(
                        f"[DbConnection] DuckDB WAL replay failure encountered ({e}). "
                        f"Quarantining {wal_path.name} to {corrupt_backup.name}...",
                        file=sys.stderr
                    )
                    shutil.move(wal_path, corrupt_backup)
                    self._conn = duckdb.connect(str(self.db_path))
                else:
                    raise
            
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

    @contextmanager
    def transaction(self):
        """
        Context manager for handling an atomic database transaction.
        Enforces atomic BEGIN TRANSACTION, COMMIT, and ROLLBACK on error.
        Yields the cached connection.
        """
        conn = self.get_connection()
        conn.execute("BEGIN TRANSACTION")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def close(self):
        """Closes the cached connection if open."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def compact_database(self) -> dict:
        """
        Compacts the DuckDB database by exporting and re-importing into a clean database file.
        Reclaims free and dead blocks left behind by incremental deletions and re-indexing passes.
        Returns a dictionary summarizing original size, compacted size, and saved bytes.
        """
        import shutil
        import tempfile

        self.close()
        if not self.db_path.exists():
            return {"status": "skipped", "reason": "database does not exist"}

        orig_size = self.db_path.stat().st_size
        temp_dir = Path(tempfile.mkdtemp(prefix="duckdb_compact_"))
        export_dir = temp_dir / "export"
        compacted_db = temp_dir / "compacted.db"

        try:
            conn = duckdb.connect(str(self.db_path), read_only=True)
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            orig_counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
            conn.execute(f"EXPORT DATABASE '{export_dir.as_posix()}'")
            conn.close()

            conn_new = duckdb.connect(str(compacted_db))
            conn_new.execute(f"IMPORT DATABASE '{export_dir.as_posix()}'")
            new_counts = {t: conn_new.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
            conn_new.close()

            for t in tables:
                if orig_counts[t] != new_counts[t]:
                    raise ValueError(
                        f"Table count mismatch during compaction for '{t}': "
                        f"{orig_counts[t]} original vs {new_counts[t]} compacted"
                    )

            compacted_size = compacted_db.stat().st_size
            backup_path = self.db_path.with_suffix(".db.bak")
            shutil.copy2(self.db_path, backup_path)
            shutil.move(compacted_db, self.db_path)
            if backup_path.exists():
                backup_path.unlink()

            return {
                "status": "success",
                "orig_size": orig_size,
                "compacted_size": compacted_size,
                "saved_bytes": orig_size - compacted_size,
                "saved_mb": round((orig_size - compacted_size) / (1024 * 1024), 2),
                "ratio": round(compacted_size / orig_size, 3) if orig_size > 0 else 1.0,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _initialize_schema(self, conn: duckdb.DuckDBPyConnection):
        """Reads schema.sql and applies it to the database connection."""
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle
            base_path = Path(sys._MEIPASS)
            schema_path = base_path / "src" / "db" / "schema.sql"
        else:
            schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            print(f"Warning: schema.sql not found at {schema_path}", file=sys.stderr)
            return

        try:
            schema_sql = schema_path.read_text(encoding="utf-8")
            # DuckDB allows executing multiple SQL statements separated by semicolons
            # We can execute the whole schema string
            conn.execute(schema_sql)
            # Ensure any stale secondary ART index on clean_symbol is removed
            conn.execute("DROP INDEX IF EXISTS idx_symbols_clean_symbol;")
        except Exception as e:
            pass

        try:
            # Gated schema migration (runs once per database via schema_version)
            schema_ver_row = conn.execute("SELECT value FROM system_metadata WHERE key = 'schema_version'").fetchone()
            current_ver = int(schema_ver_row[0]) if schema_ver_row and schema_ver_row[0].isdigit() else 1
            if current_ver < 2:
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS parent_symbol VARCHAR;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS classification VARCHAR DEFAULT '{}';")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS change_count INTEGER DEFAULT 1;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS clean_symbol VARCHAR;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS start_line INTEGER;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS start_col INTEGER;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS end_line INTEGER;")
                conn.execute("ALTER TABLE symbols ADD COLUMN IF NOT EXISTS end_col INTEGER;")
                conn.execute("ALTER TABLE edges ADD COLUMN IF NOT EXISTS call_line INTEGER;")
                conn.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS ast_sha256 VARCHAR DEFAULT '';")
                try:
                    conn.execute("DROP INDEX IF EXISTS idx_symbols_clean_symbol;")
                except Exception:
                    pass
                # Backfill clean_symbol for existing rows if null
                null_syms = conn.execute("SELECT symbol FROM symbols WHERE clean_symbol IS NULL").fetchall()
                if null_syms:
                    from utils.helpers import demangle_scip_symbol
                    updates = [(demangle_scip_symbol(s[0]), s[0]) for s in null_syms]
                    conn.executemany("UPDATE symbols SET clean_symbol = ? WHERE symbol = ?", updates)

                conn.execute(r"UPDATE files SET filepath = replace(filepath, '\', '/') WHERE filepath LIKE '%\%'")
                conn.execute(r"UPDATE symbols SET filepath = replace(filepath, '\', '/') WHERE filepath LIKE '%\%'")
                conn.execute(r"UPDATE occurrences SET filepath = replace(filepath, '\', '/') WHERE filepath LIKE '%\%'")
                conn.execute(r"UPDATE diagnostics SET filepath = replace(filepath, '\', '/') WHERE filepath LIKE '%\%'")
                conn.execute(r"UPDATE compliance_violations SET filepath = replace(filepath, '\', '/') WHERE filepath LIKE '%\%'")
                conn.execute(r"UPDATE file_co_changes SET filepath_a = replace(filepath_a, '\', '/'), filepath_b = replace(filepath_b, '\', '/') WHERE filepath_a LIKE '%\%' OR filepath_b LIKE '%\%'")
                conn.execute("INSERT INTO system_metadata (key, value) VALUES ('schema_version', '2') ON CONFLICT (key) DO UPDATE SET value = '2'")

            if current_ver < 3:
                conn.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS ast_sha256 VARCHAR DEFAULT '';")
                conn.execute("INSERT INTO system_metadata (key, value) VALUES ('schema_version', '3') ON CONFLICT (key) DO UPDATE SET value = '3'")
        except Exception as e:
            print(f"Warning during schema migration: {e}", file=sys.stderr)
