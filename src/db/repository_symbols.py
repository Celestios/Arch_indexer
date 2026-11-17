from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository, UPSERT_SYMBOL_SQL


class SymbolsRepository(BaseRepository):
    """Handles queries and updates to the 'symbols' and 'occurrences' tables."""

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
            if res:
                return {
                    "symbol": res[0],
                    "filepath": res[1],
                    "kind": res[2],
                    "signature": res[3],
                    "docstring": res[4],
                    "body_hash": res[5],
                    "connection_weight": res[6],
                    "parent_symbol": res[7],
                    "classification": res[8] or "{}",
                    "change_count": res[9] if len(res) > 9 and res[9] is not None else 1,
                    "code_block": res[10] if len(res) > 10 else None,
                    "clean_symbol": res[11] if len(res) > 11 and res[11] else res[0]
                }
        return None

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
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, filepath, start_line, start_col, end_line, end_col, role)
            )

    def get_occurrences_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Lists all physical coordinates where a symbol occurs/is used."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath, start_line, start_col, end_line, end_col, role FROM occurrences WHERE symbol = ?",
                (symbol,)
            ).fetchall()
            return [
                {
                    "filepath": r[0],
                    "start_line": r[1],
                    "start_col": r[2],
                    "end_line": r[3],
                    "end_col": r[4],
                    "role": r[5]
                }
                for r in res
            ]

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

    def add_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk inserts a list of occurrences in a single transaction."""
        if not occurrences_list:
            return
        data = [
            (
                occ["symbol"],
                occ["filepath"],
                occ["start_line"],
                occ["start_col"],
                occ["end_line"],
                occ["end_col"],
                occ["role"]
            )
            for occ in occurrences_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                data
            )
        if progress_callback:
            progress_callback(len(data), len(data))

    def get_symbols_in_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Retrieves all symbols defined inside a specific file."""
        normalized = filepath.replace("\\", "/")
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT symbol, filepath, kind, signature, docstring, body_hash, classification
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
                    "classification": r[6] or "{}"
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

    def delete_occurrences_for_file(self, filepath: str):
        """Delete all occurrences in a specific file."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM occurrences WHERE filepath = ?", (filepath,))

    def delete_symbols_for_files(self, filepaths: List[str]):
        """Delete all symbols defined in multiple files."""
        self._delete_by_filepaths("symbols", filepaths)

    def delete_occurrences_for_files(self, filepaths: List[str]):
        """Delete all occurrences in multiple files."""
        self._delete_by_filepaths("occurrences", filepaths)

    def delete_diagnostics_for_files(self, filepaths: List[str]):
        """Delete all diagnostics in multiple files."""
        self._delete_by_filepaths("diagnostics", filepaths)

    def delete_diagnostics_for_file(self, filepath: str):
        """Delete all diagnostics in a specific file."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM diagnostics WHERE filepath = ?", (filepath,))

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

    def delete_orphaned_occurrences(self) -> int:
        """Delete occurrences where the referenced symbol no longer exists in the symbols table.
        Returns the number of orphaned occurrences deleted."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                DELETE FROM occurrences
                WHERE symbol NOT IN (SELECT symbol FROM symbols)
                """
            )
            return res.rowcount if res.rowcount else 0

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
            return conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE LOWER(symbol) LIKE ? OR LOWER(COALESCE(clean_symbol, '')) LIKE ? LIMIT ?",
                (q, q, limit)
            ).fetchall()

    def search_symbols_like(self, query: str, limit: int = 10):
        """Search symbols by partial name match in symbol or clean_symbol."""
        q = f"%{query}%"
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE symbol LIKE ? OR clean_symbol LIKE ? LIMIT ?",
                (q, q, limit)
            ).fetchall()

    def get_symbol_exact(self, symbol: str):
        """Get exact symbol match (by symbol or clean_symbol)."""
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, classification, change_count, clean_symbol FROM symbols WHERE symbol = ? OR clean_symbol = ?",
                (symbol, symbol)
            ).fetchone()

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

    def get_occurrences_by_filepath(self, filepath: str):
        """Get all occurrences for a file."""
        normalized = filepath.replace("\\", "/")
        with self.db_conn.session() as conn:
            return conn.execute(
                """
                SELECT symbol, start_line, end_line, role
                FROM occurrences
                WHERE replace(filepath, '\\', '/') = ? OR filepath = ?
                """,
                (normalized, filepath)
            ).fetchall()

    def get_edges_for_symbol(self, symbol: str):
        """Get all edges where symbol is source or target."""
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT source, target, relation FROM edges WHERE source = ? OR target = ?",
                (symbol, symbol)
            ).fetchall()

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

