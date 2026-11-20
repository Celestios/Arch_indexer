import json
import logging
from typing import Dict, List, Any, Optional
from db.base import BaseRepository, UPSERT_FILE_SQL

logger = logging.getLogger(__name__)


def _normalize_path(filepath: str) -> str:
    return filepath.replace("\\", "/") if filepath else filepath


def _parse_manual_fields(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}
    return {}


class WorkspaceStore(BaseRepository):
    """
    Domain store owning workspace files, system metadata, and file co-changes.
    Enforces POSIX path normalization on ingress and utilizes clean, indexed queries.
    """

    @staticmethod
    def _format_file_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        res = dict(row)
        if "filepath" in res and res["filepath"]:
            res["filepath"] = _normalize_path(res["filepath"])
        res["manual_fields"] = _parse_manual_fields(res.get("manual_fields"))
        if "pending_audit" in res:
            res["pending_audit"] = bool(res["pending_audit"])
        return res

    # ------------------ Files Domain ------------------

    def get_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Retrieves metadata and audit state for a tracked file."""
        norm_fp = _normalize_path(filepath)
        row = self._fetch_one(
            "SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files WHERE filepath = ?",
            (norm_fp,)
        )
        return self._format_file_dict(row)

    def upsert_file(self, filepath: str, sha256: str, language: str):
        """Registers or updates a file's hashing and index metadata. Sets pending_audit if changed."""
        norm_fp = _normalize_path(filepath)
        self._execute(UPSERT_FILE_SQL, (norm_fp, sha256, language))

    def upsert_files_bulk(self, files_list: List[Dict[str, Any]]):
        """Bulk registers or updates files."""
        if not files_list:
            return
        data = [
            (_normalize_path(f["filepath"]), f["sha256"], f["language"])
            for f in files_list
        ]
        self._executemany(UPSERT_FILE_SQL, data)

    def get_all_files(self) -> List[Dict[str, Any]]:
        """Returns all tracked files with basic metadata."""
        rows = self._fetch_all(
            "SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files ORDER BY filepath"
        )
        return [self._format_file_dict(r) for r in rows if r]

    def get_all_files_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Returns dictionary of filepath -> file metadata for all files."""
        files = self.get_all_files()
        return {f["filepath"]: f for f in files if f}

    def get_pending_files(self) -> List[Dict[str, Any]]:
        """Retrieves all files marked as pending an audit check."""
        rows = self._fetch_all(
            "SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files WHERE pending_audit = TRUE"
        )
        return [self._format_file_dict(r) for r in rows if r]

    def get_files_pending_audit_count(self) -> int:
        """Returns the count of files pending audit."""
        row = self._fetch_one("SELECT COUNT(*) AS cnt FROM files WHERE pending_audit = TRUE")
        return row["cnt"] if row else 0

    def update_file_status(self, filepath: str, status: str):
        """Updates a file's compliance audit status."""
        norm_fp = _normalize_path(filepath)
        self._execute("UPDATE files SET status = ? WHERE filepath = ?", (status, norm_fp))

    def update_file_statuses(self, statuses: Dict[str, str]):
        """Batch update of file statuses."""
        if not statuses:
            return
        data = [(status, _normalize_path(fp)) for fp, status in statuses.items()]
        self._executemany("UPDATE files SET status = ? WHERE filepath = ?", data)

    def update_file_manual_status(self, filepath: str, status: str, justification: Optional[str] = None):
        """Sets a human-reviewed override status for a file and clears pending audit flag."""
        norm_fp = _normalize_path(filepath)
        self._execute(
            "UPDATE files SET manual_status = ?, pending_audit = FALSE, justification = ? WHERE filepath = ?",
            (status, justification, norm_fp)
        )

    def set_manual_fields(self, filepath: str, manual_fields: dict, justification: Optional[str] = None):
        """Sets or replaces manual metadata fields for a specific file."""
        norm_fp = _normalize_path(filepath)
        fields_json = json.dumps(manual_fields or {})
        self._execute(
            "UPDATE files SET manual_fields = ?, justification = ? WHERE filepath = ?",
            (fields_json, justification, norm_fp)
        )

    def clear_all_pending_audits(self, justification: str):
        """Marks all files as audited with a justification."""
        self._execute(
            "UPDATE files SET pending_audit = FALSE, justification = ?",
            (justification,)
        )

    def mark_file_for_audit(self, filepath: str, justification: str):
        """Explicitly sets a file's pending_audit flag."""
        norm_fp = _normalize_path(filepath)
        self._execute(
            "UPDATE files SET pending_audit = TRUE, justification = ? WHERE filepath = ?",
            (justification, norm_fp)
        )

    def delete_file_record(self, filepath: str):
        """Deletes only the record from files table."""
        norm_fp = _normalize_path(filepath)
        self._execute("DELETE FROM files WHERE filepath = ?", (norm_fp,))

    def delete_files_records(self, filepaths: List[str]):
        """Deletes multiple records from files table."""
        self._delete_by_filepaths("files", filepaths)

    def search_files(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search files by case-insensitive keyword substring in filepath."""
        q = f"%{query}%"
        rows = self._fetch_all(
            "SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files WHERE LOWER(filepath) LIKE LOWER(?) LIMIT ?",
            (q, limit)
        )
        return [self._format_file_dict(r) for r in rows if r]

    # ------------------ System Metadata Domain ------------------

    def get_metadata(self, key: str) -> Optional[str]:
        """Gets system metadata by key."""
        row = self._fetch_one("SELECT value FROM system_metadata WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str):
        """Sets system metadata key-value pair."""
        self._execute(
            """INSERT INTO system_metadata (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value)
        )

    def get_all_metadata(self) -> Dict[str, str]:
        """Gets all system metadata key-value pairs."""
        rows = self._fetch_all("SELECT key, value FROM system_metadata")
        return {r["key"]: r["value"] for r in rows}

    # ------------------ Co-changes Coupling Domain ------------------

    def record_co_changes(self, records: List[Any]):
        """Upserts a batch of CoChangeRecord tuples/objects into file_co_changes."""
        if not records:
            return
        data = []
        for r in records:
            fp_a = _normalize_path(r.filepath_a if hasattr(r, "filepath_a") else r[0])
            fp_b = _normalize_path(r.filepath_b if hasattr(r, "filepath_b") else r[1])
            count = r.co_change_count if hasattr(r, "co_change_count") else r[2]
            freq = r.frequency if hasattr(r, "frequency") else r[3]
            data.append((fp_a, fp_b, count, freq))

        self._executemany(
            """INSERT INTO file_co_changes (filepath_a, filepath_b, co_change_count, frequency)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (filepath_a, filepath_b) DO UPDATE SET
                   co_change_count = excluded.co_change_count,
                   frequency = excluded.frequency""",
            data
        )

    def get_co_changes(
        self,
        filepath: Optional[str] = None,
        min_frequency: float = 0.0,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves coupled files matching the filters."""
        if filepath:
            norm_fp = _normalize_path(filepath)
            query = """
                SELECT filepath_b, co_change_count, frequency
                FROM file_co_changes
                WHERE filepath_a = ? AND frequency >= ?
                ORDER BY frequency DESC, co_change_count DESC
            """
            params: List[Any] = [norm_fp, min_frequency]
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)
            rows = self._fetch_all(query, params)
            return [
                {
                    "filepath": _normalize_path(r["filepath_b"]),
                    "co_change_count": r["co_change_count"],
                    "frequency": r["frequency"],
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
            rows = self._fetch_all(query, params)
            return [
                {
                    "filepath_a": _normalize_path(r["filepath_a"]),
                    "filepath_b": _normalize_path(r["filepath_b"]),
                    "co_change_count": r["co_change_count"],
                    "frequency": r["frequency"],
                }
                for r in rows
            ]

    def clear_co_changes(self):
        """Clears all records in file_co_changes."""
        self._execute("DELETE FROM file_co_changes")
