from typing import Dict, List, Any, Optional, Tuple
from db.connection import DbConnection


class SymbolsRepository:
    """
    Handles queries and updates to the 'symbols' and 'occurrences' tables.
    """
    def __init__(self, db_conn: DbConnection):
        self.db_conn = db_conn

    def _query(self, sql: str, params: Optional[Tuple] = None) -> List[Any]:
        """Execute a read query and return all rows."""
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ()).fetchall()

    def _execute(self, sql: str, params: Optional[Tuple] = None) -> Any:
        """Execute a write query and return the result."""
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ())

    def upsert_symbol(
        self,
        symbol: str,
        filepath: Optional[str],
        kind: str,
        signature: Optional[str],
        docstring: Optional[str],
        body_hash: Optional[str],
        embedding: Optional[List[float]] = None,
        connection_weight: int = 0
    ):
        """
        Inserts or replaces a code symbol declaration in the database.
        filepath is optional (NULL for external third-party library dependencies).
        """
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding, connection_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    filepath = excluded.filepath,
                    kind = excluded.kind,
                    signature = excluded.signature,
                    docstring = excluded.docstring,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding,
                    connection_weight = excluded.connection_weight
                """,
                (symbol, filepath, kind, signature, docstring, body_hash, embedding, connection_weight)
            )

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a registered symbol declaration."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight FROM symbols WHERE symbol = ?",
                (symbol,)
            ).fetchone()
            if res:
                return {
                    "symbol": res[0],
                    "filepath": res[1],
                    "kind": res[2],
                    "signature": res[3],
                    "docstring": res[4],
                    "body_hash": res[5],
                    "connection_weight": res[6]
                }
        return None

    def get_symbols_by_filepaths(self, filepaths: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get all symbols for a list of filepaths, returned as {symbol: {kind, body_hash, ...}}."""
        if not filepaths:
            return {}
        result = {}
        with self.db_conn.session() as conn:
            # Build a single query with IN clause for all normalized filepaths
            fp_norms = [fp.replace("\\", "/") for fp in filepaths]
            placeholders = ",".join("?" for _ in fp_norms)
            rows = conn.execute(
                f"""SELECT symbol, kind, body_hash, signature, docstring FROM symbols
                    WHERE replace(filepath, '\\', '/') IN ({placeholders})""",
                fp_norms
            ).fetchall()
            for r in rows:
                result[r[0]] = {
                    "kind": r[1],
                    "body_hash": r[2],
                    "signature": r[3],
                    "docstring": r[4]
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
        """
        Registers a reference or definition coordinate occurrence of a symbol.
        """
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
        data = [
            (
                sym["symbol"],
                sym["filepath"],
                sym["kind"],
                sym["signature"],
                sym["docstring"],
                sym["body_hash"],
                sym.get("embedding"),
                sym.get("connection_weight", 0)
            )
            for sym in symbols_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding, connection_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    filepath = excluded.filepath,
                    kind = excluded.kind,
                    signature = excluded.signature,
                    docstring = excluded.docstring,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding,
                    connection_weight = excluded.connection_weight
                """,
                data
            )
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
                SELECT symbol, filepath, kind, signature, docstring, body_hash
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
                    "body_hash": r[5]
                }
                for r in res
            ]

    def semantic_search(self, query_embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """
        Runs a cosine similarity vector search over the docstrings of code symbols.
        """
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT 
                    symbol, 
                    filepath, 
                    kind, 
                    signature, 
                    docstring,
                    list_cosine_similarity(embedding, ?::FLOAT[]) as similarity
                FROM symbols
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT ?
                """,
                (query_embedding, limit)
            ).fetchall()
            
            return [
                {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "similarity": r[5]
                }
                for r in res
            ]

    def get_symbols_metadata_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Retrieves symbol metadata and definition occurrences in bulk.
        """
        if not symbols:
            return {}

        placeholders = ",".join("?" for _ in symbols)
        result = {}
        with self.db_conn.session() as conn:
            # 1. Fetch metadata
            sym_rows = conn.execute(
                f"SELECT symbol, filepath, kind, signature, docstring, body_hash FROM symbols WHERE symbol IN ({placeholders})",
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
                    "definition": None
                }

            # 2. Fetch definition occurrences (role & 1 == 1)
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
        if not filepaths:
            return
        with self.db_conn.session() as conn:
            conn.execute(
                "DELETE FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                (filepaths,)
            )

    def delete_occurrences_for_files(self, filepaths: List[str]):
        """Delete all occurrences in multiple files."""
        if not filepaths:
            return
        with self.db_conn.session() as conn:
            conn.execute(
                "DELETE FROM occurrences WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                (filepaths,)
            )

    def recalculate_connection_weights(self):
        """
        Recalculates connection weights (degree = incoming edges + outgoing edges) for all symbols in the database.
        Updates connection_weight in the symbols table.
        """
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE symbols SET connection_weight = 0;
                """
            )
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
        """Search symbols by keyword in name.
        
        Args:
            query: Search term (case-insensitive)
            limit: Maximum results
            
        Returns:
            List of (symbol, filepath, kind, signature, docstring) tuples
        """
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE LOWER(symbol) LIKE ? LIMIT ?",
                (f"%{query.lower()}%", limit)
            ).fetchall()

    def search_symbols_like(self, query: str, limit: int = 10):
        """Search symbols by partial name match.
        
        Args:
            query: Partial symbol name
            limit: Maximum results
            
        Returns:
            List of (symbol, filepath, kind, signature, docstring) tuples
        """
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE symbol LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            ).fetchall()

    def get_symbol_exact(self, symbol: str):
        """Get exact symbol match.
        
        Args:
            symbol: Full symbol name
            
        Returns:
            Tuple (symbol, filepath, kind, signature, docstring, body_hash) or None
        """
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash FROM symbols WHERE symbol = ?",
                (symbol,)
            ).fetchone()

    def get_occurrences_by_filepath(self, filepath: str):
        """Get all occurrences for a file.
        
        Args:
            filepath: Normalized filepath
            
        Returns:
            List of (symbol, start_line, end_line, role) tuples
        """
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
        """Get all edges where symbol is source or target.
        
        Args:
            symbol: Symbol name
            
        Returns:
            List of (source, target, relation) tuples
        """
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT source, target, relation FROM edges WHERE source = ? OR target = ?",
                (symbol, symbol)
            ).fetchall()

    def get_symbols_by_filepath_exact(self, filepath: str):
        """Get all symbols defined in a file by exact filepath.
        
        Args:
            filepath: File path
            
        Returns:
            List of (symbol, kind, signature) tuples
        """
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT symbol, kind, signature FROM symbols WHERE filepath = ?",
                (filepath,)
            ).fetchall()

    def get_all_symbols(self):
        """Returns all symbols with filepath. Used by communities.py and auditor."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath FROM symbols"
            ).fetchall()
            return [{"symbol": r[0], "filepath": r[1]} for r in res]

    def get_all_symbols_with_metadata(self):
        """Returns all symbols with full metadata. Used by auditor."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring FROM symbols"
            ).fetchall()
            return [
                {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4]
                }
                for r in res
            ]

    def update_kinds_from_codeql(self, kind_map):
        """Bulk update symbol kinds from CodeQL extraction results.
        
        Args:
            kind_map: Dict mapping symbol name to kind string
        """
        if not kind_map:
            return
        with self.db_conn.session() as conn:
            for symbol, kind in kind_map.items():
                conn.execute(
                    "UPDATE symbols SET kind = ? WHERE symbol = ?",
                    (kind, symbol)
                )

