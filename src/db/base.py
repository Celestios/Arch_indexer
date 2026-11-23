import os
import csv
import tempfile
from contextlib import contextmanager
from typing import List, Any, Optional, Dict
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
        with tempfile.NamedTemporaryFile(mode='w', newline='', suffix='.csv', delete=False, encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in rows:
                writer.writerow(['' if x is None else x for x in r])
            csv_path = f.name.replace('\\', '/')
        try:
            yield csv_path
        finally:
            try:
                os.unlink(csv_path)
            except Exception:
                pass

    def _delete_by_filepaths(self, table: str, filepaths: List[str]):
        if not filepaths:
            return
        fps = [normalize_path(fp) for fp in filepaths if fp]
        if not fps:
            return
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

UPSERT_AST_FILE_SQL = """
INSERT INTO files (filepath, sha256, ast_sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification)
VALUES (?, '', ?, ?, now(), 'COMPLIANT', 'COMPLIANT', TRUE, '{}', 'New file, pending initial audit')
ON CONFLICT (filepath) DO UPDATE SET
    ast_sha256 = excluded.ast_sha256,
    language = excluded.language
"""

# Tier-1 (Tree-sitter) owns syntactic metadata: kind, coordinates, signature, docstring, body_hash, parent_symbol
UPSERT_SYNTACTIC_SYMBOL_SQL = """
INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET
    clean_symbol = COALESCE(NULLIF(excluded.clean_symbol, ''), symbols.clean_symbol),
    filepath = COALESCE(excluded.filepath, symbols.filepath),
    kind = CASE
        WHEN excluded.kind IS NOT NULL AND excluded.kind <> 'UnspecifiedKind' THEN excluded.kind
        ELSE symbols.kind
    END,
    signature = CASE
        WHEN excluded.signature IS NOT NULL AND excluded.signature <> '' THEN excluded.signature
        ELSE symbols.signature
    END,
    docstring = CASE
        WHEN excluded.docstring IS NOT NULL AND excluded.docstring <> '' THEN excluded.docstring
        ELSE symbols.docstring
    END,
    change_count = CASE
        WHEN symbols.body_hash IS NOT NULL AND excluded.body_hash IS NOT NULL AND symbols.body_hash <> excluded.body_hash
        THEN COALESCE(symbols.change_count, 1) + 1
        ELSE COALESCE(symbols.change_count, 1)
    END,
    last_modified = CASE
        WHEN symbols.body_hash IS NOT NULL AND excluded.body_hash IS NOT NULL AND symbols.body_hash <> excluded.body_hash
        THEN now()
        ELSE symbols.last_modified
    END,
    body_hash = COALESCE(excluded.body_hash, symbols.body_hash),
    parent_symbol = COALESCE(excluded.parent_symbol, symbols.parent_symbol),
    start_line = COALESCE(excluded.start_line, symbols.start_line),
    start_col = COALESCE(excluded.start_col, symbols.start_col),
    end_line = COALESCE(excluded.end_line, symbols.end_line),
    end_col = COALESCE(excluded.end_col, symbols.end_col)
"""

UPSERT_SYNTACTIC_SYMBOLS_VECTORIZED_SQL = """
INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]),
       UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]),
       UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[])
ON CONFLICT (symbol) DO UPDATE SET
    clean_symbol = COALESCE(NULLIF(excluded.clean_symbol, ''), symbols.clean_symbol),
    filepath = COALESCE(excluded.filepath, symbols.filepath),
    kind = CASE
        WHEN excluded.kind IS NOT NULL AND excluded.kind <> 'UnspecifiedKind' THEN excluded.kind
        ELSE symbols.kind
    END,
    signature = CASE
        WHEN excluded.signature IS NOT NULL AND excluded.signature <> '' THEN excluded.signature
        ELSE symbols.signature
    END,
    docstring = CASE
        WHEN excluded.docstring IS NOT NULL AND excluded.docstring <> '' THEN excluded.docstring
        ELSE symbols.docstring
    END,
    change_count = CASE
        WHEN symbols.body_hash IS NOT NULL AND excluded.body_hash IS NOT NULL AND symbols.body_hash <> excluded.body_hash
        THEN COALESCE(symbols.change_count, 1) + 1
        ELSE COALESCE(symbols.change_count, 1)
    END,
    last_modified = CASE
        WHEN symbols.body_hash IS NOT NULL AND excluded.body_hash IS NOT NULL AND symbols.body_hash <> excluded.body_hash
        THEN now()
        ELSE symbols.last_modified
    END,
    body_hash = COALESCE(excluded.body_hash, symbols.body_hash),
    parent_symbol = COALESCE(excluded.parent_symbol, symbols.parent_symbol),
    start_line = COALESCE(excluded.start_line, symbols.start_line),
    start_col = COALESCE(excluded.start_col, symbols.start_col),
    end_line = COALESCE(excluded.end_line, symbols.end_line),
    end_col = COALESCE(excluded.end_col, symbols.end_col)
"""

# Tier-2 (SCIP) owns semantic identity and fills syntactic fields only when absent (SCIP-only / external symbols)
UPSERT_SEMANTIC_SYMBOL_SQL = """
INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET
    clean_symbol = COALESCE(NULLIF(symbols.clean_symbol, ''), excluded.clean_symbol),
    filepath = COALESCE(symbols.filepath, excluded.filepath),
    kind = CASE
        WHEN symbols.kind IS NOT NULL AND symbols.kind <> 'UnspecifiedKind' THEN symbols.kind
        ELSE excluded.kind
    END,
    signature = CASE
        WHEN symbols.signature IS NOT NULL AND symbols.signature <> '' THEN symbols.signature
        ELSE excluded.signature
    END,
    docstring = CASE
        WHEN symbols.docstring IS NOT NULL AND symbols.docstring <> '' THEN symbols.docstring
        ELSE excluded.docstring
    END,
    body_hash = COALESCE(symbols.body_hash, excluded.body_hash),
    parent_symbol = COALESCE(symbols.parent_symbol, excluded.parent_symbol),
    start_line = COALESCE(symbols.start_line, excluded.start_line),
    start_col = COALESCE(symbols.start_col, excluded.start_col),
    end_line = COALESCE(symbols.end_line, excluded.end_line),
    end_col = COALESCE(symbols.end_col, excluded.end_col)
"""

UPSERT_SEMANTIC_SYMBOLS_VECTORIZED_SQL = """
INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]),
       UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]),
       UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[])
ON CONFLICT (symbol) DO UPDATE SET
    clean_symbol = COALESCE(NULLIF(symbols.clean_symbol, ''), excluded.clean_symbol),
    filepath = COALESCE(symbols.filepath, excluded.filepath),
    kind = CASE
        WHEN symbols.kind IS NOT NULL AND symbols.kind <> 'UnspecifiedKind' THEN symbols.kind
        ELSE excluded.kind
    END,
    signature = CASE
        WHEN symbols.signature IS NOT NULL AND symbols.signature <> '' THEN symbols.signature
        ELSE excluded.signature
    END,
    docstring = CASE
        WHEN symbols.docstring IS NOT NULL AND symbols.docstring <> '' THEN symbols.docstring
        ELSE excluded.docstring
    END,
    body_hash = COALESCE(symbols.body_hash, excluded.body_hash),
    parent_symbol = COALESCE(symbols.parent_symbol, excluded.parent_symbol),
    start_line = COALESCE(symbols.start_line, excluded.start_line),
    start_col = COALESCE(symbols.start_col, excluded.start_col),
    end_line = COALESCE(symbols.end_line, excluded.end_line),
    end_col = COALESCE(symbols.end_col, excluded.end_col)
"""

UPSERT_EDGE_SQL = """
INSERT INTO edges (source, target, relation, weight, call_line)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (source, target, relation) DO UPDATE SET
    weight = excluded.weight,
    call_line = COALESCE(excluded.call_line, edges.call_line)
"""

UPSERT_EDGES_VECTORIZED_SQL = """
INSERT INTO edges (source, target, relation, weight, call_line)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]),
       UNNEST(?::DOUBLE[]), UNNEST(?::INTEGER[])
ON CONFLICT (source, target, relation) DO UPDATE SET
    weight = excluded.weight,
    call_line = COALESCE(excluded.call_line, edges.call_line)
"""

UPSERT_OCCURRENCES_VECTORIZED_SQL = """
INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
SELECT UNNEST(?::VARCHAR[]), UNNEST(?::VARCHAR[]), UNNEST(?::INTEGER[]),
       UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[]), UNNEST(?::INTEGER[])
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
