import json
import logging
from typing import Any, Dict, List, Optional

from db.base import (
    BaseRepository,
    UPSERT_AST_FILE_SQL,
    UPSERT_FILE_SQL,
    UPSERT_FILES_VECTORIZED_SQL,
    normalize_path,
)

logger = logging.getLogger(__name__)


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
    Domain store owning workspace files and system metadata.
    Enforces POSIX path normalization on ingress.
    """

    @staticmethod
    def _format_file_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        res = dict(row)
        if res.get("filepath"):
            res["filepath"] = normalize_path(res["filepath"])
        res["manual_fields"] = _parse_manual_fields(res.get("manual_fields"))
        if "pending_audit" in res:
            res["pending_audit"] = bool(res["pending_audit"])
        return res

    # ------------------ Files Domain ------------------

    def get_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Retrieves metadata and audit state for a tracked file."""
        norm_fp = normalize_path(filepath)
        row = self._fetch_one(
            "SELECT filepath, sha256, ast_sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files WHERE filepath = ?",
            (norm_fp,),
        )
        return self._format_file_dict(row)

    def resolve_filepath(self, raw_path: str) -> Optional[str]:
        """Resolves a filepath against tracked files via exact match then POSIX suffix fallback."""
        norm_raw = normalize_path(raw_path)
        if not norm_raw:
            return None
        if self.get_file(norm_raw):
            return norm_raw
        row = self._fetch_one(
            "SELECT filepath FROM files WHERE ends_with(filepath, ?) ORDER BY length(filepath) ASC LIMIT 1",
            (norm_raw,),
        )
        return normalize_path(row["filepath"]) if row else None

    def get_all_files(self) -> List[Dict[str, Any]]:
        """Returns all tracked files with metadata."""
        rows = self._fetch_all(
            "SELECT filepath, sha256, ast_sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files ORDER BY filepath"
        )
        return [self._format_file_dict(r) for r in rows if r]

    def get_all_files_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Returns dictionary of filepath -> file metadata for all files."""
        return {f["filepath"]: f for f in self.get_all_files() if f}

    def get_files_pending_audit_count(self) -> int:
        """Returns the count of files pending audit."""
        row = self._fetch_one("SELECT COUNT(*) AS cnt FROM files WHERE pending_audit = TRUE")
        return row["cnt"] if row else 0

    def search_files(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Case-insensitive substring search in filepath."""
        q = f"%{query}%"
        rows = self._fetch_all(
            "SELECT filepath, sha256, ast_sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification FROM files WHERE LOWER(filepath) LIKE LOWER(?) LIMIT ?",
            (q, limit),
        )
        return [self._format_file_dict(r) for r in rows if r]

    def upsert_file(self, filepath: str, sha256: str, language: str):
        """Registers or updates a file's hash and index metadata."""
        self._execute(UPSERT_FILE_SQL, (normalize_path(filepath), sha256, language))

    def upsert_ast_file(self, filepath: str, ast_sha256: str, language: str):
        """Registers or updates a file's Tier-1 AST hash without altering Tier-2 SCIP sha256."""
        self._execute(UPSERT_AST_FILE_SQL, (normalize_path(filepath), ast_sha256, language))

    def upsert_files(self, files_list: List[Dict[str, Any]]):
        """Bulk registers or updates files using vectorized UNNEST."""
        if not files_list:
            return
        fps = [normalize_path(f["filepath"]) for f in files_list]
        hashes = [f["sha256"] for f in files_list]
        langs = [f["language"] for f in files_list]
        self._execute(UPSERT_FILES_VECTORIZED_SQL, (fps, hashes, langs))

    def update_file_statuses(self, statuses: Dict[str, str]):
        """Vectorized batch update of file compliance statuses."""
        if not statuses:
            return
        stats = list(statuses.values())
        fps = [normalize_path(fp) for fp in statuses.keys()]
        self._execute(
            """UPDATE files
               SET status = u.s
               FROM (
                   SELECT UNNEST(?::VARCHAR[]) AS s,
                          UNNEST(?::VARCHAR[]) AS f
               ) u
               WHERE files.filepath = u.f""",
            (stats, fps),
        )

    def update_file_manual_status(self, filepath: str, status: str, justification: Optional[str] = None):
        """Sets a manual override status for a file and clears its pending audit flag."""
        self._execute(
            "UPDATE files SET manual_status = ?, pending_audit = FALSE, justification = ? WHERE filepath = ?",
            (status, justification, normalize_path(filepath)),
        )

    def update_manual_fields(self, filepath: str, manual_fields: dict, justification: Optional[str] = None):
        """Replaces manual metadata fields for a specific file."""
        fields_json = json.dumps(manual_fields or {})
        self._execute(
            "UPDATE files SET manual_fields = ?, justification = ? WHERE filepath = ?",
            (fields_json, justification, normalize_path(filepath)),
        )

    def update_clear_pending_audits(self, justification: str):
        """Marks all files as audited with a justification."""
        self._execute(
            "UPDATE files SET pending_audit = FALSE, justification = ?",
            (justification,),
        )

    def update_mark_file_pending(self, filepath: str, justification: str):
        """Explicitly flags a file as pending audit."""
        self._execute(
            "UPDATE files SET pending_audit = TRUE, justification = ? WHERE filepath = ?",
            (justification, normalize_path(filepath)),
        )

    # ------------------ System Metadata Domain ------------------

    def get_metadata(self, key: str) -> Optional[str]:
        """Gets system metadata by key."""
        row = self._fetch_one("SELECT value FROM system_metadata WHERE key = ?", (key,))
        return row["value"] if row else None

    def upsert_metadata(self, key: str, value: str):
        """Upserts a system metadata key-value pair."""
        self._execute(
            """INSERT INTO system_metadata (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
