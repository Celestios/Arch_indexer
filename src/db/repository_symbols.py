from typing import Dict, List, Any, Optional
from db.base import BaseRepository

class SymbolsRepository(BaseRepository):
    """
    Handles queries and updates to the 'symbols' and 'occurrences' tables.
    """

    def upsert_symbol(
        self,
        symbol: str,
        filepath: Optional[str],
        kind: str,
        signature: Optional[str],
        docstring: Optional[str],
        body_hash: Optional[str],
        embedding: Optional[List[float]] = None
    ):
        """
        Inserts or replaces a code symbol declaration in the database.
        filepath is optional (NULL for external third-party library dependencies).
        """
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    filepath = excluded.filepath,
                    kind = excluded.kind,
                    signature = excluded.signature,
                    docstring = excluded.docstring,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding
                """,
                (symbol, filepath, kind, signature, docstring, body_hash, embedding)
            )

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a registered symbol declaration."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash FROM symbols WHERE symbol = ?",
                (symbol,)
            ).fetchone()
            if res:
                return {
                    "symbol": res[0],
                    "filepath": res[1],
                    "kind": res[2],
                    "signature": res[3],
                    "docstring": res[4],
                    "body_hash": res[5]
                }
        return None

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

    def upsert_symbols_bulk(self, symbols_list: List[Dict[str, Any]]):
        """Bulk upserts a list of symbols in a single transaction."""
        data = [
            (
                sym["symbol"],
                sym["filepath"],
                sym["kind"],
                sym["signature"],
                sym["docstring"],
                sym["body_hash"],
                sym.get("embedding")
            )
            for sym in symbols_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    filepath = excluded.filepath,
                    kind = excluded.kind,
                    signature = excluded.signature,
                    docstring = excluded.docstring,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding
                """,
                data
            )

    def add_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]]):
        """Bulk inserts a list of occurrences in a single transaction."""
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
