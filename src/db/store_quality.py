import uuid
import logging
from typing import Dict, List, Any, Optional
from db.base import (
    BaseRepository,
    UPSERT_VIOLATION_SQL,
    UPSERT_VIOLATIONS_VECTORIZED_SQL,
    UPSERT_DIAGNOSTICS_VECTORIZED_SQL,
    normalize_path,
)

logger = logging.getLogger(__name__)


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
            (rule_id, description, severity),
        )

    def get_rules(self) -> List[Dict[str, Any]]:
        """Retrieves all registered compliance rules."""
        return self._fetch_all("SELECT rule_id, description, severity FROM compliance_rules")

    # ------------------ Violations Domain ------------------

    def upsert_violation(
        self,
        violation_id: str,
        rule_id: str,
        symbol: Optional[str],
        filepath: str,
        line: int,
        message: str,
        origin: str = "automatic",
    ) -> str:
        """Upserts a single compliance violation."""
        self._execute(
            UPSERT_VIOLATION_SQL,
            (violation_id, rule_id, symbol, normalize_path(filepath), line, message, origin),
        )
        return violation_id

    def upsert_violations(self, violations: List[Dict[str, Any]]):
        """Bulk upserts compliance violations using vectorized UNNEST."""
        if not violations:
            return
        v_ids = [v.get("violation_id") or f"viol_{uuid.uuid4().hex[:12]}" for v in violations]
        r_ids = [v.get("rule_id") for v in violations]
        syms = [v.get("symbol") for v in violations]
        fps = [normalize_path(v["filepath"]) for v in violations]
        lines = [int(v["line"]) for v in violations]
        msgs = [v["message"] for v in violations]
        origins = [v.get("origin", "automatic") for v in violations]
        self._execute(
            UPSERT_VIOLATIONS_VECTORIZED_SQL,
            (v_ids, r_ids, syms, fps, lines, msgs, origins),
        )

    def get_violations(
        self,
        filepath: Optional[str] = None,
        rule_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves recorded violations joined with compliance_rules for severity and description."""
        query = """
            SELECT v.violation_id, v.rule_id, r.description, v.symbol, v.filepath, v.line, v.message, r.severity, v.checked_at, v.origin
            FROM compliance_violations v
            LEFT JOIN compliance_rules r ON v.rule_id = r.rule_id
            WHERE 1=1
        """
        params: List[Any] = []
        if filepath:
            query += " AND v.filepath = ?"
            params.append(normalize_path(filepath))
        if rule_id:
            query += " AND v.rule_id = ?"
            params.append(rule_id)
        query += " ORDER BY r.severity DESC, v.filepath ASC, v.line ASC"
        rows = self._fetch_all(query, params)
        return [
            {
                "violation_id": r["violation_id"],
                "rule_id": r["rule_id"],
                "rule_description": r.get("description") or "Manual Logical Audit",
                "symbol": r.get("symbol"),
                "filepath": normalize_path(r["filepath"]),
                "line": r["line"],
                "message": r["message"],
                "severity": r.get("severity") or "WARNING",
                "checked_at": r.get("checked_at"),
                "origin": r.get("origin") or "automatic",
            }
            for r in rows
        ]

    def delete_violations(
        self,
        filepath: Optional[str] = None,
        filepath_prefix: Optional[str] = None,
        rule_ids: Optional[List[str]] = None,
        origin: Optional[str] = None,
    ):
        """Selectively deletes violations matching filepath, prefix, rule_ids, or origin."""
        query = "DELETE FROM compliance_violations WHERE 1=1"
        params: List[Any] = []
        if origin:
            query += " AND origin = ?"
            params.append(origin)
        if filepath:
            query += " AND filepath = ?"
            params.append(normalize_path(filepath))
        if filepath_prefix:
            query += " AND filepath LIKE ?"
            params.append(f"{normalize_path(filepath_prefix)}%")
        if rule_ids:
            query += " AND rule_id IN (SELECT UNNEST(?::VARCHAR[]))"
            params.append(rule_ids)
        self._execute(query, params)

    # ------------------ Diagnostics Domain ------------------

    def upsert_diagnostics(self, diagnostics_list: List[Dict[str, Any]]):
        """Bulk inserts compiler/analyzer diagnostics using vectorized UNNEST."""
        if not diagnostics_list:
            return
        fps = [normalize_path(diag["filepath"]) for diag in diagnostics_list]
        syms = [diag.get("symbol") for diag in diagnostics_list]
        lines = [int(diag.get("line", 1)) for diag in diagnostics_list]
        cols = [int(diag.get("col", 0)) for diag in diagnostics_list]
        sevs = [diag.get("severity", "Error") for diag in diagnostics_list]
        codes = [diag.get("code") for diag in diagnostics_list]
        msgs = [diag.get("message", "") for diag in diagnostics_list]
        tags = [diag.get("tags") for diag in diagnostics_list]
        self._execute(
            UPSERT_DIAGNOSTICS_VECTORIZED_SQL,
            (fps, syms, lines, cols, sevs, codes, msgs, tags),
        )

    def get_diagnostics(
        self,
        filepath: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Returns diagnostics filtered by filepath and/or symbol."""
        query = "SELECT filepath, symbol, line, col, severity, code, message, tags FROM diagnostics WHERE 1=1"
        params: List[Any] = []
        if filepath:
            query += " AND filepath = ?"
            params.append(normalize_path(filepath))
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        rows = self._fetch_all(query, params)
        for r in rows:
            r["filepath"] = normalize_path(r["filepath"])
        return rows

    def get_diagnostics_batch(self, symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Batch fetch diagnostics mapped by symbol."""
        if not symbols:
            return {}
        rows = self._fetch_all(
            "SELECT filepath, symbol, line, col, severity, code, message, tags FROM diagnostics WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
            (symbols,),
        )
        mapping: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            r["filepath"] = normalize_path(r["filepath"])
            sym = r.get("symbol")
            if sym:
                mapping.setdefault(sym, []).append(r)
        return mapping

    def delete_diagnostics(self, filepaths: List[str]):
        """Deletes diagnostics for multiple files."""
        self._delete_by_filepaths("diagnostics", filepaths)
