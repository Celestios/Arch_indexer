from typing import List, Any, Optional, Tuple, Dict
from db.connection import DbConnection


def normalize_path(filepath: Optional[str]) -> str:
    """Canonical POSIX path normalization for database persistence."""
    return filepath.replace("\\", "/") if filepath else ""


class BaseRepository:
    """Shared base class for all repository and store implementations. Eliminates DRY violations."""

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

    def _delete_by_filepaths(self, table: str, filepaths: List[str]):
        if not filepaths:
            return
        fps = [normalize_path(fp) for fp in filepaths]
        self._execute(
            f"DELETE FROM {table} WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
            (fps,)
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
INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET
    clean_symbol = COALESCE(NULLIF(excluded.clean_symbol, ''), symbols.clean_symbol),
    filepath = COALESCE(excluded.filepath, symbols.filepath),
    kind = CASE 
        WHEN symbols.kind IS NOT NULL AND symbols.kind <> 'UnspecifiedKind' THEN symbols.kind 
        ELSE excluded.kind 
    END,
    signature = CASE 
        WHEN excluded.signature IS NOT NULL AND excluded.signature <> '' THEN excluded.signature 
        ELSE symbols.signature 
    END,
    docstring = CASE 
        WHEN excluded.docstring IS NOT NULL AND excluded.docstring <> '' THEN excluded.docstring 
        ELSE symbols.docstring 
    END,
    change_count = CASE WHEN symbols.body_hash <> excluded.body_hash THEN COALESCE(symbols.change_count, 1) + 1 ELSE COALESCE(symbols.change_count, 1) END,
    last_modified = CASE WHEN symbols.body_hash <> excluded.body_hash THEN now() ELSE symbols.last_modified END,
    body_hash = COALESCE(excluded.body_hash, symbols.body_hash),
    connection_weight = excluded.connection_weight,
    parent_symbol = COALESCE(excluded.parent_symbol, symbols.parent_symbol),
    start_line = COALESCE(excluded.start_line, symbols.start_line),
    start_col = COALESCE(excluded.start_col, symbols.start_col),
    end_line = COALESCE(excluded.end_line, symbols.end_line),
    end_col = COALESCE(excluded.end_col, symbols.end_col)
"""

UPSERT_EDGE_SQL = """
INSERT INTO edges (source, target, relation, weight, call_line)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (source, target, relation) DO UPDATE SET
    weight = excluded.weight,
    call_line = COALESCE(excluded.call_line, edges.call_line)
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
