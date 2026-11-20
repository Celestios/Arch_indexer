from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository


class OccurrencesRepository(BaseRepository):
    """Handles queries and updates to the 'occurrences' table."""

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

    def upsert_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]], progress_callback=None):
        """Alias for add_occurrences_bulk."""
        self.add_occurrences_bulk(occurrences_list, progress_callback=progress_callback)

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

    def get_definitions_map(self) -> Dict[str, Dict[str, Any]]:
        """Returns all definition occurrences as {symbol: {filepath, start_line, ...}} in one query."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT symbol, filepath, start_line, start_col, end_line, end_col, role
                FROM occurrences
                WHERE (role & 1) = 1
                """
            ).fetchall()
            result = {}
            for r in res:
                result[r[0]] = {
                    "filepath": r[1],
                    "start_line": r[2],
                    "start_col": r[3],
                    "end_line": r[4],
                    "end_col": r[5],
                    "role": r[6],
                }
            return result

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

    def delete_occurrences_for_file(self, filepath: str):
        """Delete all occurrences in a specific file."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM occurrences WHERE filepath = ?", (filepath,))

    def delete_occurrences_for_files(self, filepaths: List[str]):
        """Delete all occurrences in multiple files."""
        self._delete_by_filepaths("occurrences", filepaths)

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
