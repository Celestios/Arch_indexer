import json
from typing import Dict, List, Any, Optional
from db.connection import DbConnection
from db.base import BaseRepository, UPSERT_FILE_SQL


class FilesRepository(BaseRepository):
    """Handles queries and updates to the 'files' table."""

    def upsert_file(self, filepath: str, sha256: str, language: str):
        """Registers or updates a file's hashing and index metadata. Sets pending_audit if changed."""
        with self.db_conn.session() as conn:
            conn.execute(UPSERT_FILE_SQL, (filepath, sha256, language))

    def delete_file(self, filepath: str):
        """
        Deletes a file record and cleans up associated symbols, occurrences, and edges.
        Delegates cross-table cleanup to CascadeCleanupService.
        """
        from db.cascade import CascadeCleanupService
        cascade = CascadeCleanupService(self._get_repository())
        cascade.delete_file(filepath)

    def delete_file_record(self, filepath: str):
        """Deletes only the file record (no cross-table cleanup)."""
        with self.db_conn.session() as conn:
            conn.execute("DELETE FROM files WHERE filepath = ?", (filepath,))

    def delete_files_records(self, filepaths: List[str]):
        """Deletes only file records for multiple files (no cross-table cleanup)."""
        self._delete_by_filepaths("files", filepaths)

    def _get_repository(self):
        """Get the parent Repository for cascade operations."""
        from db.repository import Repository
        return Repository(self.db_conn)

    def get_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Retrieves indexing metadata for a specific file."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files WHERE filepath = ?",
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
                    "pending_audit": bool(res[6]),
                    "manual_fields": res[7],
                    "justification": res[8]
                }
        return None

    def upsert_files_bulk(self, files_list: List[Dict[str, Any]]):
        """Bulk upserts a list of files in a single transaction. Sets pending_audit on change."""
        if not files_list:
            return
        data = [
            (
                f["filepath"],
                f["sha256"],
                f["language"]
            )
            for f in files_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(UPSERT_FILE_SQL, data)

    def update_file_manual_status(self, filepath: str, status: str, justification: Optional[str] = None):
        """Sets the manual compliance status for a file and clears pending_audit."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET manual_status = ?,
                    pending_audit = FALSE,
                    justification = ?
                WHERE filepath = ?
                """,
                (status, justification, filepath)
            )

    def update_file_manual_fields(self, filepath: str, manual_fields: dict, justification: Optional[str] = None):
        """Sets or updates the manual metadata fields (JSON format) for a file."""
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
                "UPDATE files SET status = ? WHERE filepath = ?",
                (status, filepath)
            )

    def get_all_files_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves all files' status, manual status, pending_audit, manual fields, justification, and sha256."""
        with self.db_conn.session() as conn:
            rows = conn.execute(
                "SELECT filepath, sha256, status, manual_status, pending_audit, manual_fields, justification, language FROM files"
            ).fetchall()
            metadata = {}
            for r in rows:
                try:
                    manual_fields = json.loads(r[5]) if r[5] else {}
                except Exception:
                    manual_fields = {}
                metadata[r[0]] = {
                    "filepath": r[0],
                    "sha256": r[1],
                    "status": r[2],
                    "manual_status": r[3],
                    "pending_audit": bool(r[4]),
                    "manual_fields": manual_fields,
                    "justification": r[6],
                    "language": r[7]
                }
            return metadata

    def clear_all_pending_audits(self, justification: str):
        """Sets pending_audit = FALSE for all files in the database."""
        with self.db_conn.session() as conn:
            conn.execute(
                "UPDATE files SET pending_audit = FALSE, justification = ?",
                (justification,)
            )

    def get_files_pending_audit_count(self) -> int:
        """Returns the count of files with pending_audit = TRUE."""
        with self.db_conn.session() as conn:
            result = conn.execute(
                "SELECT COUNT(*) FROM files WHERE pending_audit = TRUE"
            ).fetchone()
            return result[0] if result else 0

    def clean_files_symbols_and_relations(self, filepaths: List[str]):
        """Cleans up occurrences, edges, and symbols for the given filepaths before re-ingesting."""
        if not filepaths:
            return
        from db.cascade import CascadeCleanupService
        cascade = CascadeCleanupService(self._get_repository())
        cascade.delete_files_bulk(filepaths)

    def update_file_statuses(self, statuses):
        """Bulk update file compliance statuses."""
        if not statuses:
            return
        data = [(status, filepath) for filepath, status in statuses.items()]
        with self.db_conn.session() as conn:
            conn.executemany(
                "UPDATE files SET status = ? WHERE filepath = ?",
                data
            )

    def mark_file_for_audit(self, filepath: str, justification: str):
        """Mark a file as pending audit with a justification."""
        with self.db_conn.session() as conn:
            conn.execute(
                "UPDATE files SET pending_audit = TRUE, justification = ? WHERE filepath = ?",
                (justification, filepath)
            )

    def search_files_keyword(self, query: str, limit: int = 5):
        """Search files by keyword in filepath."""
        with self.db_conn.session() as conn:
            return conn.execute(
                "SELECT filepath, language, status FROM files WHERE LOWER(filepath) LIKE ? LIMIT ?",
                (f"%{query.lower()}%", limit)
            ).fetchall()

    def get_file_exact(self, filepath: str):
        """Get exact file match by filepath."""
        normalized = filepath.replace("\\", "/")
        with self.db_conn.session() as conn:
            return conn.execute(
                """
                SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification
                FROM files
                WHERE filepath = ? OR replace(filepath, '\\', '/') = ?
                """,
                (filepath, normalized)
            ).fetchone()

    def search_files_like(self, query: str, limit: int = 10):
        """Search files by partial filepath match."""
        normalized = query.replace("\\", "/")
        with self.db_conn.session() as conn:
            return conn.execute(
                """
                SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification
                FROM files
                WHERE replace(filepath, '\\', '/') LIKE ? OR replace(filepath, '\\', '/') = ?
                LIMIT ?
                """,
                (f"%{normalized}%", normalized, limit)
            ).fetchall()
