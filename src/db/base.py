from typing import List, Any, Optional, Tuple
from db.connection import DbConnection


class BaseRepository:
    """Shared base class for all repository implementations. Eliminates DRY violations."""

    def __init__(self, db_conn: DbConnection):
        self.db_conn = db_conn

    def _query(self, sql: str, params: Optional[Tuple] = None) -> List[Any]:
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ()).fetchall()

    def _execute(self, sql: str, params: Optional[Tuple] = None) -> Any:
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ())

    def _delete_by_filepaths(self, table: str, filepaths: List[str]):
        if not filepaths:
            return
        self._execute(
            f"DELETE FROM {table} WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
            (filepaths,)
        )

    def _delete_by_filepaths_unnest(self, table: str, filepaths: List[str]):
        if not filepaths:
            return
        self._execute(
            f"DELETE FROM {table} WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
            (filepaths,)
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

UPSERT_SYMBOL_SQL = """
INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, connection_weight)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET
    filepath = excluded.filepath,
    kind = excluded.kind,
    signature = excluded.signature,
    docstring = excluded.docstring,
    body_hash = excluded.body_hash,
    connection_weight = excluded.connection_weight
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
