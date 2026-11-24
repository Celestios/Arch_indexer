import csv
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from db.connection import DbConnection


def normalize_path(filepath: Optional[str]) -> Optional[str]:
    """Canonical POSIX path normalization for database persistence."""
    return filepath.replace("\\", "/") if filepath else None


class BaseRepository:
    """Shared base class for all domain stores."""

    def __init__(self, db_conn: DbConnection):
        self._db_conn = db_conn

    def _fetch_one(self, sql: str, params: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        with self._db_conn.session() as conn:
            cursor = conn.execute(sql, params or ())
            if not cursor.description:
                return None
            cols = [c[0] for c in cursor.description]
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(zip(cols, row))

    def _fetch_all(self, sql: str, params: Optional[Any] = None) -> List[Dict[str, Any]]:
        with self._db_conn.session() as conn:
            cursor = conn.execute(sql, params or ())
            if not cursor.description:
                return []
            cols = [c[0] for c in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(cols, r)) for r in rows]

    def _execute(self, sql: str, params: Optional[Any] = None) -> Any:
        with self._db_conn.session() as conn:
            return conn.execute(sql, params or ())

    def _executemany(self, sql: str, seq_of_params: List[Any]) -> Any:
        with self._db_conn.session() as conn:
            return conn.executemany(sql, seq_of_params)

    @contextmanager
    def _csv_staging(self, headers: List[str], rows: List[List[Any]]):
        """Streams row data into a temporary CSV file for zero-boxing C++ read_csv bulk loading."""
        with tempfile.NamedTemporaryFile(mode="w", newline="", suffix=".csv", delete=False, encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in rows:
                writer.writerow(["" if x is None else x for x in r])
            csv_path = f.name.replace("\\", "/")
        try:
            yield csv_path
        finally:
            try:
                os.unlink(csv_path)
            except OSError:
                pass

    def _delete_by_filepaths(self, table: str, filepaths: List[str]):
        if not filepaths:
            return
        fps = [normalize_path(fp) for fp in filepaths if fp]
        if not fps:
            return
        self._execute(
            f"DELETE FROM {table} WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
            (fps,),
        )


UPSERT_FILE_SQL = """
INSERT INTO files (filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification)
VALUES (?, ?, ?, now(), 'COMPLIANT', 'COMPLIANT', TRUE, '{}', 'New file, pending initial audit')
ON CONFLICT (filepath) DO UPDATE SET
    pending_audit = CASE WHEN files.sha256 <> excluded.sha256 THEN TRUE ELSE files.pending_audit END,
    justification = CASE WHEN files.sha256 <> excluded.sha256 THEN 'File modified, pending re-audit' ELSE files.justification END,
    sha256 = excluded.sha256,
    language = excluded.language,
    last_indexed = now()
"""

UPSERT_AST_FILE_SQL = """
INSERT INTO files (filepath, sha256, ast_sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification)
VALUES (?, '', ?, ?, now(), 'COMPLIANT', 'COMPLIANT', TRUE, '{}', 'New file, pending initial audit')
ON CONFLICT (filepath) DO UPDATE SET
    ast_sha256 = excluded.ast_sha256,
    language = excluded.language
"""

UPSERT_FILES_VECTORIZED_SQL = """
INSERT INTO files (filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]),
       now(), 'COMPLIANT', 'COMPLIANT', TRUE, '{}', 'New file, pending initial audit'
ON CONFLICT (filepath) DO UPDATE SET
    pending_audit = CASE WHEN files.sha256 <> excluded.sha256 THEN TRUE ELSE files.pending_audit END,
    justification = CASE WHEN files.sha256 <> excluded.sha256 THEN 'File modified, pending re-audit' ELSE files.justification END,
    sha256 = excluded.sha256,
    language = excluded.language,
    last_indexed = now()
"""

UPSERT_VIOLATION_SQL = """
INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message, origin)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (violation_id) DO UPDATE SET
    rule_id = excluded.rule_id,
    symbol = excluded.symbol,
    filepath = excluded.filepath,
    line = excluded.line,
    message = excluded.message,
    origin = excluded.origin
"""

UPSERT_VIOLATIONS_VECTORIZED_SQL = """
INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message, origin)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]),
       UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[])
ON CONFLICT (violation_id) DO UPDATE SET
    rule_id = excluded.rule_id,
    symbol = excluded.symbol,
    filepath = excluded.filepath,
    line = excluded.line,
    message = excluded.message,
    origin = excluded.origin
"""

UPSERT_DIAGNOSTICS_VECTORIZED_SQL = """
INSERT INTO diagnostics (filepath, symbol, line, col, severity, code, message, tags)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]),
       UNNEST(?::INTEGER[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]),
       UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[])
"""
