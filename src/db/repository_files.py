from typing import Dict, List, Any, Optional
from db.base import BaseRepository

class FilesRepository(BaseRepository):
    """
    Handles queries and updates to the 'files' table.
    """

    def upsert_file(self, filepath: str, sha256: str, language: str):
        """Registers or updates a file's hashing and index metadata. Resets manual_status if changed."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO files (filepath, sha256, language, last_indexed, status, manual_status, manual_fields, justification)
                VALUES (?, ?, ?, now(), 'COMPLIANT', 'PENDING_AUDIT', '{}', 'New file, pending initial audit')
                ON CONFLICT (filepath) DO UPDATE SET
                    manual_status = CASE WHEN files.sha256 <> excluded.sha256 THEN 'PENDING_AUDIT' ELSE files.manual_status END,
                    justification = CASE WHEN files.sha256 <> excluded.sha256 THEN 'File modified, pending re-audit' ELSE files.justification END,
                    sha256 = excluded.sha256,
                    language = excluded.language,
                    last_indexed = now()
                """,
                (filepath, sha256, language)
            )

    def delete_file(self, filepath: str):
        """
        Deletes a file record and manually cleans up associated symbols, occurrences, and edges
        to maintain referential integrity.
        """
        with self.db_conn.session() as conn:
            # 1. Delete outgoing or incoming edges linking to symbols in this file
            conn.execute(
                """
                DELETE FROM edges 
                WHERE source IN (SELECT symbol FROM symbols WHERE filepath = ?)
                   OR target IN (SELECT symbol FROM symbols WHERE filepath = ?)
                """,
                (filepath, filepath)
            )
            # 2. Delete occurrences in this file
            conn.execute("DELETE FROM occurrences WHERE filepath = ?", (filepath,))
            # 3. Delete symbols in this file
            conn.execute("DELETE FROM symbols WHERE filepath = ?", (filepath,))
            # 4. Delete the file itself
            conn.execute("DELETE FROM files WHERE filepath = ?", (filepath,))

    def get_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Retrieves indexing metadata for a specific file."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath, sha256, language, last_indexed, status, manual_status, manual_fields, justification FROM files WHERE filepath = ?",
                (filepath,)
            ).fetchone()
            if res:
                return {
                    "filepath": res[0],
                    "sha256": res[1],
                    "language": res[2],
                    "last_indexed": res[3],
                    "status": res[4],
                    "manual_status": res[5],
                    "manual_fields": res[6],
                    "justification": res[7]
                }
        return None

    def upsert_files_bulk(self, files_list: List[Dict[str, Any]]):
        """Bulk upserts a list of files in a single transaction. Resets manual_status on change."""
        data = [
            (
                f["filepath"],
                f["sha256"],
                f["language"]
            )
            for f in files_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO files (filepath, sha256, language, last_indexed, status, manual_status, manual_fields, justification)
                VALUES (?, ?, ?, now(), 'COMPLIANT', 'PENDING_AUDIT', '{}', 'New file, pending initial audit')
                ON CONFLICT (filepath) DO UPDATE SET
                    manual_status = CASE WHEN files.sha256 <> excluded.sha256 THEN 'PENDING_AUDIT' ELSE files.manual_status END,
                    justification = CASE WHEN files.sha256 <> excluded.sha256 THEN 'File modified, pending re-audit' ELSE files.justification END,
                    sha256 = excluded.sha256,
                    language = excluded.language,
                    last_indexed = now()
                """,
                data
            )

    def update_file_manual_status(self, filepath: str, status: str, justification: Optional[str] = None):
        """Sets the manual compliance status for a file."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET manual_status = ?,
                    justification = ?
                WHERE filepath = ?
                """,
                (status, justification, filepath)
            )

    def update_file_manual_fields(self, filepath: str, manual_fields: dict, justification: Optional[str] = None):
        """Sets or updates the manual metadata fields (JSON format) for a file."""
        import json
        fields_str = json.dumps(manual_fields)
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET manual_fields = ?,
                    justification = ?
                WHERE filepath = ?
                """,
                (fields_str, justification, filepath)
            )

    def update_file_status(self, filepath: str, status: str):
        """Updates the automatically evaluated compliance status for a file."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET status = ?
                WHERE filepath = ?
                """,
                (status, filepath)
            )

    def get_all_files_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves all files' status, manual status, manual fields and justification."""
        import json
        with self.db_conn.session() as conn:
            rows = conn.execute(
                "SELECT filepath, status, manual_status, manual_fields, justification FROM files"
            ).fetchall()
            metadata = {}
            for r in rows:
                try:
                    manual_fields = json.loads(r[3]) if r[3] else {}
                except Exception:
                    manual_fields = {}
                metadata[r[0]] = {
                    "filepath": r[0],
                    "status": r[1],
                    "manual_status": r[2],
                    "manual_fields": manual_fields,
                    "justification": r[4]
                }
            return metadata
