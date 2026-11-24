import logging
import random
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "5"
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / ".arch" / "arch.db"

_LOCK_ERROR_MARKERS = (
    "cannot open file",
    "file is already open",
    "conflicting lock",
    "could not set lock",
    "being used by another process",
    "lock on file",
)


def _is_lock_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _LOCK_ERROR_MARKERS)


class DbConnection:
    """Manages DuckDB database connections, transient lock retry, fail-fast schema verification, and transactions."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, lock_timeout: float = 10.0):
        self.db_path = Path(db_path)
        self.lock_timeout = float(lock_timeout)
        self._initialized = False
        self._conn = None

    def _connect_with_retry(self) -> duckdb.DuckDBPyConnection:
        """Opens DuckDB with jittered exponential backoff on transient cross-process lock contention."""
        deadline = time.monotonic() + max(0.0, self.lock_timeout)
        delay = 0.05
        attempt = 0

        while True:
            try:
                return duckdb.connect(str(self.db_path))
            except Exception as e:
                wal_path = self.db_path.with_name(self.db_path.name + ".wal")
                if "Failure while replaying WAL file" in str(e) and wal_path.exists():
                    corrupt_backup = self.db_path.with_name(self.db_path.name + ".wal.corrupt")
                    logger.warning(
                        "DuckDB WAL replay failure (%s). Quarantining %s to %s.",
                        e,
                        wal_path.name,
                        corrupt_backup.name,
                    )
                    shutil.move(wal_path, corrupt_backup)
                    return duckdb.connect(str(self.db_path))

                if _is_lock_error(e):
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        attempt += 1
                        sleep_for = min(delay * random.uniform(0.75, 1.25), remaining)
                        if attempt == 1 or attempt % 10 == 0:
                            logger.debug(
                                "DuckDB lock contention on %s (attempt %d); retrying in %.2fs",
                                self.db_path.name,
                                attempt,
                                sleep_for,
                            )
                        time.sleep(sleep_for)
                        delay = min(delay * 1.5, 0.30)
                        continue
                raise

    def get_connection(self) -> duckdb.DuckDBPyConnection:
        """Creates and caches a DuckDB connection for the active session, verifying schema version."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self._conn is None:
            self._conn = self._connect_with_retry()
            if not self._initialized:
                self._initialize_schema(self._conn)
                self._initialized = True
        return self._conn

    @contextmanager
    def session(self):
        """Yields the cached connection without closing it for fast intra-operation query reuse."""
        conn = self.get_connection()
        yield conn

    @contextmanager
    def scoped_session(self):
        """Opens DuckDB for a single unit of work and closes it on exit to release OS file locks."""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.close()

    @contextmanager
    def transaction(self):
        """Enforces atomic BEGIN TRANSACTION, COMMIT, and ROLLBACK on error."""
        conn = self.get_connection()
        conn.execute("BEGIN TRANSACTION")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def close(self):
        """Closes the cached connection if open, flushing WAL and releasing the OS file lock."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._initialized = False

    def compact_database(self) -> dict:
        """Exports and re-imports the DuckDB file to reclaim free/dead blocks."""
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
        """Fast-path schema version check; applies schema.sql only on uninitialized DBs (fail-fast, no migrations)."""
        try:
            ver_row = conn.execute(
                "SELECT value FROM system_metadata WHERE key = 'schema_version'"
            ).fetchone()
        except duckdb.CatalogException:
            ver_row = None

        if ver_row is not None:
            if str(ver_row[0]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Incompatible database schema version '{ver_row[0]}' (expected '{SCHEMA_VERSION}'). "
                    "Rebuild the index with 'arch init --force'."
                )
            return

        if getattr(sys, "frozen", False):
            schema_path = Path(sys._MEIPASS) / "src" / "db" / "schema.sql"
        else:
            schema_path = Path(__file__).parent / "schema.sql"

        if not schema_path.exists():
            raise FileNotFoundError(f"Database schema file not found at {schema_path}")

        schema_sql = schema_path.read_text(encoding="utf-8")
        conn.execute(schema_sql)
        conn.execute(
            "INSERT INTO system_metadata (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,),
        )
