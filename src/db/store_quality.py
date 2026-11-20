import uuid
import logging
from typing import Dict, List, Any, Optional
from db.base import BaseRepository, UPSERT_VIOLATION_SQL

logger = logging.getLogger(__name__)


def _normalize_path(filepath: Optional[str]) -> Optional[str]:
    return filepath.replace("\\", "/") if filepath else None


class QualityStore(BaseRepository):
    """
    Domain store owning compliance rules, violations, and compiler diagnostics.
    Enforces POSIX path normalization on ingress.
    """

    # ------------------ Compliance Rules Domain ------------------

    def upsert_rule(self, rule_id: str, description: str, severity: str):
        """Registers or updates a compliance rule."""
        self._execute(
            """INSERT INTO compliance_rules (rule_id, description, severity)
               VALUES (?, ?, ?)
               ON CONFLICT (rule_id) DO UPDATE SET
                   description = excluded.description,
                   severity = excluded.severity""",
            (rule_id, description, severity)
        )

    def get_rules(self) -> List[Dict[str, Any]]:
        """Retrieves all registered compliance rules."""
        return self._fetch_all("SELECT rule_id, description, severity FROM compliance_rules")

    # ------------------ Violations Domain ------------------

    def add_violation(
        self,
        violation_id: str,
        rule_id: str,
        symbol: Optional[str],
        filepath: str,
        line: int,
        message: str,
        origin: str = "automatic"
    ) -> str:
        """Inserts a single violation."""
        norm_fp = _normalize_path(filepath)
        self._execute(
            UPSERT_VIOLATION_SQL,
            (violation_id, rule_id, symbol, norm_fp, line, message, origin)
        )
        return violation_id

    def record_violations_bulk(self, violations: List[Dict[str, Any]]):
        """Bulk inserts or updates compliance violations."""
        if not violations:
            return
        data = [
            (
                v.get("violation_id") or f"viol_{uuid.uuid4().hex[:12]}",
                v.get("rule_id"),
                v.get("symbol"),
                _normalize_path(v["filepath"]),
                v["line"],
                v["message"],
                v.get("origin", "automatic"),
            )
            for v in violations
        ]
        self._executemany(UPSERT_VIOLATION_SQL, data)

    def get_violations(
        self,
        filepath: Optional[str] = None,
        rule_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieves recorded violations with optional filters, joined with rules for severity."""
        query = """
            SELECT v.violation_id, v.rule_id, r.description, v.symbol, v.filepath, v.line, v.message, r.severity, v.checked_at, v.origin
            FROM compliance_violations v
            LEFT JOIN compliance_rules r ON v.rule_id = r.rule_id
            WHERE 1=1
        """
        params: List[Any] = []
        if filepath:
            norm_fp = _normalize_path(filepath)
            query += " AND v.filepath = ?"
            params.append(norm_fp)
        if rule_id:
            query += " AND v.rule_id = ?"
            params.append(rule_id)
        query += " ORDER BY r.severity DESC, v.filepath ASC, v.line ASC"
        rows = self._fetch_all(query, params)
        res = []
        for r in rows:
            res.append({
                "violation_id": r["violation_id"],
                "rule_id": r["rule_id"],
                "rule_description": r.get("description") or "Manual Logical Audit",
                "symbol": r.get("symbol"),
                "filepath": _normalize_path(r["filepath"]),
                "line": r["line"],
                "message": r["message"],
                "severity": r.get("severity") or "WARNING",
                "checked_at": r.get("checked_at"),
                "origin": r.get("origin") or "automatic",
            })
        return res

    def clear_violations(
        self,
        filepath_prefix: Optional[str] = None,
        rule_ids: Optional[List[str]] = None,
        origin: Optional[str] = None
    ):
        """Selectively clears violations."""
        query = "DELETE FROM compliance_violations WHERE 1=1"
        params: List[Any] = []
        if origin:
            query += " AND origin = ?"
            params.append(origin)
        if filepath_prefix:
            norm_prefix = _normalize_path(filepath_prefix)
            query += " AND filepath LIKE ?"
            params.append(f"{norm_prefix}%")
        if rule_ids:
            query += " AND rule_id IN (SELECT UNNEST(?::VARCHAR[]))"
            params.append(rule_ids)
        self._execute(query, params)

    def delete_manual_violations(self, filepath: str):
        """Deletes manual violations for a file."""
        norm_fp = _normalize_path(filepath)
        self._execute(
            "DELETE FROM compliance_violations WHERE filepath = ? AND origin = 'manual'",
            (norm_fp,)
        )

    def delete_automatic_violations(self, rule_ids: Optional[List[str]] = None):
        """Deletes automatic violations, optionally filtered by rule IDs."""
        if rule_ids:
            self._execute(
                "DELETE FROM compliance_violations WHERE origin = 'automatic' AND rule_id IN (SELECT UNNEST(?::VARCHAR[]))",
                (rule_ids,)
            )
        else:
            self._execute("DELETE FROM compliance_violations WHERE origin = 'automatic'")

    def delete_automatic_violations_for_path(self, filepath_prefix: str):
        """Deletes automatic violations for files matching prefix."""
        norm_p = _normalize_path(filepath_prefix)
        self._execute(
            "DELETE FROM compliance_violations WHERE origin = 'automatic' AND filepath LIKE ?",
            (f"{norm_p}%",)
        )

    # ------------------ Diagnostics Domain ------------------

    def record_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk inserts compiler/analyzer diagnostics."""
        if not diagnostics_list:
            return
        data = [
            (
                _normalize_path(diag["filepath"]),
                diag.get("symbol"),
                diag["line"],
                diag.get("col", 0),
                diag.get("severity", "Error"),
                diag.get("code"),
                diag.get("message", ""),
                diag.get("tags"),
            )
            for diag in diagnostics_list
        ]
        self._executemany(
            "INSERT INTO diagnostics (filepath, symbol, line, col, severity, code, message, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            data
        )
        if progress_callback:
            progress_callback(len(data), len(data))

    def add_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Alias for record_diagnostics_bulk."""
        self.record_diagnostics_bulk(diagnostics_list, progress_callback)

    def upsert_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None):
        """Alias for record_diagnostics_bulk."""
        self.record_diagnostics_bulk(diagnostics_list, progress_callback)

    def get_diagnostics_for_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Returns diagnostics for a given file."""
        norm_fp = _normalize_path(filepath)
        rows = self._fetch_all(
            "SELECT filepath, symbol, line, col, severity, code, message, tags FROM diagnostics WHERE filepath = ?",
            (norm_fp,)
        )
        for r in rows:
            r["filepath"] = _normalize_path(r["filepath"])
        return rows

    def get_diagnostics_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns diagnostics attached to a symbol."""
        rows = self._fetch_all(
            "SELECT filepath, symbol, line, col, severity, code, message, tags FROM diagnostics WHERE symbol = ?",
            (symbol,)
        )
        for r in rows:
            r["filepath"] = _normalize_path(r["filepath"])
        return rows

    def get_diagnostics_batch(self, symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Batch fetch diagnostics for multiple symbols."""
        if not symbols:
            return {}
        rows = self._fetch_all(
            "SELECT filepath, symbol, line, col, severity, code, message, tags FROM diagnostics WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
            (symbols,)
        )
        result: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            r["filepath"] = _normalize_path(r["filepath"])
            sym = r["symbol"]
            result.setdefault(sym, []).append(r)
        return result

    def delete_diagnostics_for_file(self, filepath: str):
        """Deletes diagnostics for a given file."""
        norm_fp = _normalize_path(filepath)
        self._execute("DELETE FROM diagnostics WHERE filepath = ?", (norm_fp,))

    def delete_diagnostics_for_files(self, filepaths: List[str]):
        """Deletes diagnostics for multiple files."""
        self._delete_by_filepaths("diagnostics", filepaths)
