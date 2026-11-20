from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository


class DiagnosticsRepository(BaseRepository):
    """Handles queries and updates to the 'diagnostics' table."""

    def add_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk inserts a list of diagnostics in a single transaction."""
        if not diagnostics_list:
            return
        data = [
            (
                d["filepath"],
                d.get("symbol"),
                d["line"],
                d["col"],
                d["severity"],
                d.get("code"),
                d["message"],
                d.get("tags")
            )
            for d in diagnostics_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO diagnostics (filepath, symbol, line, col, severity, code, message, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                data
            )
        if progress_callback:
            progress_callback(len(data), len(data))

    def upsert_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Alias for add_diagnostics_bulk."""
        self.add_diagnostics_bulk(diagnostics_list, progress_callback=progress_callback)

    def get_diagnostics_for_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Get all diagnostics recorded for a specific file."""
        normalized = filepath.replace("\\", "/")
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT filepath, symbol, line, col, severity, code, message, tags
                FROM diagnostics
                WHERE replace(filepath, '\\', '/') = ? OR filepath = ?
                ORDER BY line, col
                """,
                (normalized, filepath)
            ).fetchall()
            return [
                {
                    "filepath": r[0],
                    "symbol": r[1],
                    "line": r[2],
                    "col": r[3],
                    "severity": r[4],
                    "code": r[5],
                    "message": r[6],
                    "tags": r[7]
                }
                for r in res
            ]

    def get_diagnostics_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Get all diagnostics recorded for a specific symbol."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT filepath, symbol, line, col, severity, code, message, tags
                FROM diagnostics
                WHERE symbol = ?
                ORDER BY line, col
                """,
                (symbol,)
            ).fetchall()
            return [
                {
                    "filepath": r[0],
                    "symbol": r[1],
                    "line": r[2],
                    "col": r[3],
                    "severity": r[4],
                    "code": r[5],
                    "message": r[6],
                    "tags": r[7]
                }
                for r in res
            ]

    def get_diagnostics_batch(self, symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get all diagnostics recorded for a batch of symbols, returned as {symbol: [diag, ...]}."""
        if not symbols:
            return {}
        result: Dict[str, List[Dict[str, Any]]] = {sym: [] for sym in symbols}
        unique_symbols = list(set(symbols))
        chunk_size = 500
        with self.db_conn.session() as conn:
            for i in range(0, len(unique_symbols), chunk_size):
                chunk = unique_symbols[i:i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                res = conn.execute(
                    f"""
                    SELECT filepath, symbol, line, col, severity, code, message, tags
                    FROM diagnostics
                    WHERE symbol IN ({placeholders})
                    ORDER BY line, col
                    """,
                    chunk
                ).fetchall()
                for r in res:
                    sym = r[1]
                    diag = {
                        "filepath": r[0],
                        "symbol": sym,
                        "line": r[2],
                        "col": r[3],
                        "severity": r[4],
                        "code": r[5],
                        "message": r[6],
                        "tags": r[7]
                    }
                    if sym in result:
                        result[sym].append(diag)
                    else:
                        result[sym] = [diag]
        return result

    def delete_diagnostics_for_file(self, filepath: str):
        """Delete all diagnostics in a specific file."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM diagnostics WHERE filepath = ?", (filepath,))

    def delete_diagnostics_for_files(self, filepaths: List[str]):
        """Delete all diagnostics in multiple files."""
        self._delete_by_filepaths("diagnostics", filepaths)
