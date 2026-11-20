from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository, RowDict, UPSERT_SYMBOL_SQL


class SymbolsRepository(BaseRepository):
    """Handles queries and updates to the 'symbols' table and delegates occurrence/diagnostic leaf queries."""

    def __init__(self, db_conn: DbConnection, occurrences=None, diagnostics=None, edges=None):
        super().__init__(db_conn)
        self.occurrences = occurrences
        self.diagnostics = diagnostics
        self.edges = edges

    def _get_occurrences(self):
        if self.occurrences is not None:
            return self.occurrences
        from db.repository_occurrences import OccurrencesRepository
        self.occurrences = OccurrencesRepository(self.db_conn)
        return self.occurrences

    def _get_diagnostics(self):
        if self.diagnostics is not None:
            return self.diagnostics
        from db.repository_diagnostics import DiagnosticsRepository
        self.diagnostics = DiagnosticsRepository(self.db_conn)
        return self.diagnostics

    def _get_edges(self):
        if self.edges is not None:
            return self.edges
        from db.repository_edges import EdgesRepository
        self.edges = EdgesRepository(self.db_conn)
        return self.edges

    @staticmethod
    def _row_to_symbol_dict(row) -> Optional[Dict[str, Any]]:
        """Maps a database row tuple to a normalized symbol dict/RowDict."""
        if not row:
            return None
        if isinstance(row, RowDict):
            return row
        if isinstance(row, dict):
            return row
        if len(row) == 5:
            order = ["symbol", "filepath", "kind", "signature", "docstring"]
            data = {
                "symbol": row[0],
                "filepath": row[1],
                "kind": row[2],
                "signature": row[3],
                "docstring": row[4],
            }
            return RowDict(data, order)
        elif len(row) == 11:
            order = [
                "symbol", "filepath", "kind", "signature", "docstring",
                "body_hash", "connection_weight", "parent_symbol",
                "classification", "change_count", "clean_symbol"
            ]
            clean_sym = row[10] if row[10] else None
            if not clean_sym and row[0]:
                from utils.helpers import demangle_scip_symbol
                clean_sym = demangle_scip_symbol(row[0])
            data = {
                "symbol": row[0],
                "filepath": row[1],
                "kind": row[2],
                "signature": row[3],
                "docstring": row[4],
                "body_hash": row[5],
                "connection_weight": row[6] if row[6] is not None else 0,
                "parent_symbol": row[7],
                "classification": row[8] or "{}",
                "change_count": row[9] if row[9] is not None else 1,
                "code_block": None,
                "clean_symbol": clean_sym
            }
            return RowDict(data, order)
        else:
            order = [
                "symbol", "filepath", "kind", "signature", "docstring",
                "body_hash", "connection_weight", "parent_symbol",
                "classification", "change_count", "code_block", "clean_symbol"
            ]
            clean_sym = row[11] if len(row) > 11 and row[11] else (row[10] if len(row) == 11 and row[10] else None)
            if not clean_sym and row[0]:
                from utils.helpers import demangle_scip_symbol
                clean_sym = demangle_scip_symbol(row[0])
            data = {
                "symbol": row[0],
                "filepath": row[1],
                "kind": row[2],
                "signature": row[3],
                "docstring": row[4],
                "body_hash": row[5] if len(row) > 5 else None,
                "connection_weight": row[6] if len(row) > 6 and row[6] is not None else 0,
                "parent_symbol": row[7] if len(row) > 7 else None,
                "classification": row[8] if len(row) > 8 and row[8] else "{}",
                "change_count": row[9] if len(row) > 9 and row[9] is not None else 1,
                "code_block": row[10] if len(row) > 10 else None,
                "clean_symbol": clean_sym,
            }
            return RowDict(data, order)

    def upsert_symbol(
        self,
        symbol: str,
        filepath: Optional[str],
        kind: str,
        signature: Optional[str],
        docstring: Optional[str],
        body_hash: Optional[str],
        connection_weight: int = 0,
        parent_symbol: Optional[str] = None,
        code_block: Optional[str] = None,
        clean_symbol: Optional[str] = None,
    ):
        """Inserts or replaces a code symbol declaration in the database."""
        if clean_symbol is None and symbol:
            from utils.helpers import demangle_scip_symbol
            clean_symbol = demangle_scip_symbol(symbol)
        with self.db_conn.session() as conn:
            conn.execute(UPSERT_SYMBOL_SQL, (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, code_block))

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a registered symbol declaration."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, classification, change_count, code_block, clean_symbol FROM symbols WHERE symbol = ? OR clean_symbol = ?",
                (symbol, symbol)
            ).fetchone()
            return self._row_to_symbol_dict(res)

    def get_symbols_by_filepaths(self, filepaths: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get all symbols for a list of filepaths, returned as {symbol: {kind, body_hash, ...}}."""
        if not filepaths:
            return {}
        result = {}
        fp_norms = [fp.replace("\\", "/") for fp in filepaths]
        placeholders = ",".join("?" for _ in fp_norms)
        with self.db_conn.session() as conn:
            rows = conn.execute(
                f"""SELECT symbol, kind, body_hash, signature, docstring, filepath, parent_symbol, classification, code_block, clean_symbol FROM symbols
                    WHERE replace(filepath, '\\', '/') IN ({placeholders})""",
                fp_norms
            ).fetchall()
            for r in rows:
                result[r[0]] = {
                    "kind": r[1],
                    "body_hash": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "filepath": r[5],
                    "parent_symbol": r[6],
                    "classification": r[7] or "{}",
                    "code_block": r[8] if len(r) > 8 else None,
                    "clean_symbol": r[9] if len(r) > 9 and r[9] else r[0]
                }
        return result

    def upsert_symbols_bulk(self, symbols_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk upserts a list of symbols in a single transaction."""
        if not symbols_list:
            return
        from utils.helpers import demangle_scip_symbol
        data = [
            (
                sym["symbol"],
                sym.get("clean_symbol") or demangle_scip_symbol(sym["symbol"]),
                sym["filepath"],
                sym["kind"],
                sym["signature"],
                sym["docstring"],
                sym["body_hash"],
                sym.get("connection_weight", 0),
                sym.get("parent_symbol"),
                sym.get("code_block"),
            )
            for sym in symbols_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(UPSERT_SYMBOL_SQL, data)
        if progress_callback:
            progress_callback(len(data), len(data))

    def get_symbols_in_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Retrieves all symbols defined inside a specific file."""
        normalized = filepath.replace("\\", "/")
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT symbol, filepath, kind, signature, docstring, body_hash, classification, parent_symbol
                FROM symbols
                WHERE replace(filepath, '\\', '/') = ? OR filepath = ?
                """,
                (normalized, filepath)
            ).fetchall()
            return [
                {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "body_hash": r[5],
                    "classification": r[6] or "{}",
                    "parent_symbol": r[7] if len(r) > 7 else None
                }
                for r in res
            ]

    def get_symbols_metadata_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Retrieves symbol metadata and definition occurrences in bulk."""
        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        result = {}
        with self.db_conn.session() as conn:
            sym_rows = conn.execute(
                f"SELECT symbol, filepath, kind, signature, docstring, body_hash, classification FROM symbols WHERE symbol IN ({placeholders})",
                symbols
            ).fetchall()
            for r in sym_rows:
                result[r[0]] = {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "body_hash": r[5],
                    "classification": r[6] or "{}",
                    "definition": None
                }
            occ_rows = conn.execute(
                f"""
                SELECT symbol, filepath, start_line, start_col, end_line, end_col, role 
                FROM occurrences 
                WHERE symbol IN ({placeholders}) AND (role & 1) = 1
                """,
                symbols
            ).fetchall()
            for r in occ_rows:
                sym_name = r[0]
                if sym_name in result:
                    result[sym_name]["definition"] = {
                        "filepath": r[1],
                        "start_line": r[2],
                        "start_col": r[3],
                        "end_line": r[4],
                        "end_col": r[5],
                        "role": r[6]
                    }
        return result

    def delete_symbols_for_file(self, filepath: str):
        """Delete all symbols defined in a specific file."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM symbols WHERE filepath = ?", (filepath,))

    def delete_symbols_for_files(self, filepaths: List[str]):
        """Delete all symbols defined in multiple files."""
        self._delete_by_filepaths("symbols", filepaths)

    def recalculate_connection_weights(self):
        """Recalculates connection weights for all symbols in the database."""
        with self.db_conn.session() as conn:
            conn.execute("UPDATE symbols SET connection_weight = 0;")
            conn.execute(
                """
                WITH degree_counts AS (
                    SELECT source AS sym, COUNT(*) AS cnt FROM edges GROUP BY source
                    UNION ALL
                    SELECT target AS sym, COUNT(*) AS cnt FROM edges GROUP BY target
                ),
                total_degrees AS (
                    SELECT sym, SUM(cnt) AS total_cnt
                    FROM degree_counts
                    GROUP BY sym
                )
                UPDATE symbols
                SET connection_weight = total_degrees.total_cnt
                FROM total_degrees
                WHERE symbols.symbol = total_degrees.sym
                """
            )

    def search_symbols_keyword(self, query: str, limit: int = 5):
        """Search symbols by keyword in symbol or clean_symbol."""
        q = f"%{query.lower()}%"
        with self.db_conn.session() as conn:
            rows = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE LOWER(symbol) LIKE ? OR LOWER(COALESCE(clean_symbol, '')) LIKE ? LIMIT ?",
                (q, q, limit)
            ).fetchall()
            return [self._row_to_symbol_dict(r) for r in rows]

    def search_symbols_like(self, query: str, limit: int = 10):
        """Search symbols by partial name match in symbol or clean_symbol."""
        q = f"%{query}%"
        with self.db_conn.session() as conn:
            rows = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE symbol LIKE ? OR clean_symbol LIKE ? LIMIT ?",
                (q, q, limit)
            ).fetchall()
            return [self._row_to_symbol_dict(r) for r in rows]

    def get_symbol_exact(self, symbol: str):
        """Get exact symbol match (by symbol or clean_symbol)."""
        with self.db_conn.session() as conn:
            row = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, classification, change_count, clean_symbol FROM symbols WHERE symbol = ? OR clean_symbol = ?",
                (symbol, symbol)
            ).fetchone()
            return self._row_to_symbol_dict(row)

    def update_symbols_classification_bulk(self, classifications: Dict[str, Dict[str, Any]]):
        """Bulk updates computed classification fields for symbols."""
        if not classifications:
            return
        import json
        data = [
            (json.dumps(fields) if isinstance(fields, dict) else str(fields), sym)
            for sym, fields in classifications.items()
        ]
        with self.db_conn.session() as conn:
            conn.executemany("UPDATE symbols SET classification = ? WHERE symbol = ?", data)

    def get_symbols_by_filepath_exact(self, filepath: str):
        """Get all symbols defined in a file by exact filepath."""
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, kind, signature FROM symbols WHERE filepath = ?",
                (filepath,)
            ).fetchall()

    def get_all_symbols(self):
        """Returns all symbols with filepath."""
        with self.db_conn.session() as conn:
            res = conn.execute("SELECT symbol, filepath FROM symbols").fetchall()
            return [{"symbol": r[0], "filepath": r[1]} for r in res]

    def get_all_symbols_with_metadata(self):
        """Returns all symbols with full metadata."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, clean_symbol FROM symbols"
            ).fetchall()
            return [
                {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "clean_symbol": r[5] if len(r) > 5 and r[5] else r[0]
                }
                for r in res
            ]

    # --- Delegated Occurrence Methods (Backwards Compatibility) ---

    def add_occurrence(
        self,
        symbol: str,
        filepath: str,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
        role: int
    ):
        """Registers a reference or definition coordinate occurrence of a symbol."""
        self._get_occurrences().add_occurrence(symbol, filepath, start_line, start_col, end_line, end_col, role)

    def add_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk inserts a list of occurrences in a single transaction."""
        self._get_occurrences().add_occurrences_bulk(occurrences_list, progress_callback=progress_callback)

    def upsert_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]], progress_callback=None):
        """Alias for add_occurrences_bulk."""
        self._get_occurrences().upsert_occurrences_bulk(occurrences_list, progress_callback=progress_callback)

    def get_occurrences_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Lists all physical coordinates where a symbol occurs/is used."""
        return self._get_occurrences().get_occurrences_for_symbol(symbol)

    def get_definitions_map(self) -> Dict[str, Dict[str, Any]]:
        """Returns all definition occurrences as {symbol: {filepath, start_line, ...}} in one query."""
        return self._get_occurrences().get_definitions_map()

    def get_occurrences_by_filepath(self, filepath: str):
        """Get all occurrences for a file."""
        return self._get_occurrences().get_occurrences_by_filepath(filepath)

    def delete_occurrences_for_file(self, filepath: str):
        """Delete all occurrences in a specific file."""
        self._get_occurrences().delete_occurrences_for_file(filepath)

    def delete_occurrences_for_files(self, filepaths: List[str]):
        """Delete all occurrences in multiple files."""
        self._get_occurrences().delete_occurrences_for_files(filepaths)

    def delete_orphaned_occurrences(self) -> int:
        """Delete occurrences where the referenced symbol no longer exists in the symbols table."""
        return self._get_occurrences().delete_orphaned_occurrences()

    # --- Delegated Diagnostic Methods (Backwards Compatibility) ---

    def add_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk inserts a list of diagnostics in a single transaction."""
        self._get_diagnostics().add_diagnostics_bulk(diagnostics_list, progress_callback=progress_callback)

    def upsert_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Alias for add_diagnostics_bulk."""
        self._get_diagnostics().upsert_diagnostics_bulk(diagnostics_list, progress_callback=progress_callback)

    def get_diagnostics_for_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Get all diagnostics recorded for a specific file."""
        return self._get_diagnostics().get_diagnostics_for_file(filepath)

    def get_diagnostics_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Get all diagnostics recorded for a specific symbol."""
        return self._get_diagnostics().get_diagnostics_for_symbol(symbol)

    def get_diagnostics_batch(self, symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get all diagnostics recorded for a batch of symbols."""
        return self._get_diagnostics().get_diagnostics_batch(symbols)

    def delete_diagnostics_for_file(self, filepath: str):
        """Delete all diagnostics in a specific file."""
        self._get_diagnostics().delete_diagnostics_for_file(filepath)

    def delete_diagnostics_for_files(self, filepaths: List[str]):
        """Delete all diagnostics in multiple files."""
        self._get_diagnostics().delete_diagnostics_for_files(filepaths)

    # --- Delegated Edge Methods (Backwards Compatibility) ---

    def get_edges_for_symbol(self, symbol: str):
        """Get all edges where symbol is source or target."""
        return self._get_edges().get_edges_for_symbol(symbol)
