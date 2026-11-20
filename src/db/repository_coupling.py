from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository


class CouplingRepository(BaseRepository):
    """Handles queries and updates to the 'file_co_changes' table."""

    def clear(self):
        """Clears all records from the file_co_changes table."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM file_co_changes")

    def upsert_bulk(self, records: List[Any]):
        """Bulk upserts co-change frequency records into file_co_changes."""
        if not records:
            return
        data = []
        for r in records:
            if isinstance(r, dict):
                data.append((r["filepath_a"], r["filepath_b"], r["co_change_count"], r["frequency"]))
            else:
                data.append((r[0], r[1], r[2], r[3]))
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO file_co_changes (filepath_a, filepath_b, co_change_count, frequency)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (filepath_a, filepath_b) DO UPDATE SET
                    co_change_count = excluded.co_change_count,
                    frequency = excluded.frequency
                """,
                data
            )

    def get_co_changes(
        self,
        filepath: Optional[str] = None,
        min_frequency: float = 0.0,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves file co-changes, optionally filtered by filepath and minimum frequency."""
        with self.db_conn.session() as conn:
            if filepath:
                norm_fp = filepath.replace("\\", "/")
                query = """
                    SELECT filepath_b, co_change_count, frequency
                    FROM file_co_changes
                    WHERE (replace(filepath_a, '\\', '/') = ? OR filepath_a = ?)
                      AND frequency >= ?
                    ORDER BY frequency DESC, co_change_count DESC
                """
                params: List[Any] = [norm_fp, filepath, min_frequency]
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)
                rows = conn.execute(query, params).fetchall()
                return [
                    {
                        "filepath": r[0],
                        "co_change_count": r[1],
                        "frequency": r[2]
                    }
                    for r in rows
                ]
            else:
                query = """
                    SELECT filepath_a, filepath_b, co_change_count, frequency
                    FROM file_co_changes
                    WHERE frequency >= ?
                    ORDER BY frequency DESC, co_change_count DESC
                """
                params = [min_frequency]
                if limit is not None:
                    query += " LIMIT ?"
                    params.append(limit)
                rows = conn.execute(query, params).fetchall()
                return [
                    {
                        "filepath_a": r[0],
                        "filepath_b": r[1],
                        "co_change_count": r[2],
                        "frequency": r[3]
                    }
                    for r in rows
                ]
