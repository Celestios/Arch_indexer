from typing import Dict, Optional
from db.connection import DbConnection
from db.base import BaseRepository


class MetadataRepository(BaseRepository):
    """Handles queries and updates to the 'system_metadata' table."""

    def get(self, key: str) -> Optional[str]:
        """Retrieves a metadata value by key."""
        with self.db_conn.session() as conn:
            res = conn.execute("SELECT value FROM system_metadata WHERE key = ?", (key,)).fetchone()
            return res[0] if res else None

    def set(self, key: str, value: str):
        """Sets or updates a metadata key-value pair."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO system_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value
                """,
                (key, value)
            )

    def get_all(self) -> Dict[str, str]:
        """Retrieves all metadata key-value pairs."""
        with self.db_conn.session() as conn:
            rows = conn.execute("SELECT key, value FROM system_metadata").fetchall()
            return {r[0]: r[1] for r in rows}
