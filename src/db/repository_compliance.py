from typing import Dict, List, Any, Optional, Tuple
from db.connection import DbConnection


class ComplianceRepository:
    """
    Handles queries and updates to compliance rules and violations tables.
    """
    def __init__(self, db_conn: DbConnection):
        self.db_conn = db_conn

    def _query(self, sql: str, params: Optional[Tuple] = None) -> List[Any]:
        """Execute a read query and return all rows."""
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ()).fetchall()

    def _execute(self, sql: str, params: Optional[Tuple] = None) -> Any:
        """Execute a write query and return the result."""
        with self.db_conn.session() as conn:
            return conn.execute(sql, params or ())

    def upsert_compliance_rule(self, rule_id: str, description: str, severity: str):
        """Stores or updates an architectural safety boundary rule."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO compliance_rules (rule_id, description, severity)
                VALUES (?, ?, ?)
                ON CONFLICT (rule_id) DO UPDATE SET
                    description = excluded.description,
                    severity = excluded.severity
                """,
                (rule_id, description, severity)
            )

    def add_violation(
        self,
        violation_id: str,
        rule_id: str,
        symbol: Optional[str],
        filepath: str,
        line: int,
        message: str,
        origin: str = "automatic"
    ):
        """Registers an architectural boundary violation."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (violation_id) DO UPDATE SET
                    rule_id = excluded.rule_id,
                    symbol = excluded.symbol,
                    filepath = excluded.filepath,
                    line = excluded.line,
                    message = excluded.message,
                    origin = excluded.origin
                """,
                (violation_id, rule_id, symbol, filepath, line, message, origin)
            )

    def get_violations(self) -> List[Dict[str, Any]]:
        """Retrieves all registered compliance violations sorted by threat severity."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT v.violation_id, v.rule_id, r.description, v.symbol, v.filepath, v.line, v.message, r.severity, v.checked_at, v.origin
                FROM compliance_violations v
                LEFT JOIN compliance_rules r ON v.rule_id = r.rule_id
                ORDER BY r.severity DESC, v.filepath ASC
                """
            ).fetchall()
            return [
                {
                    "violation_id": r[0],
                    "rule_id": r[1],
                    "rule_description": r[2] or "Manual Logical Audit",
                    "symbol": r[3],
                    "filepath": r[4],
                    "line": r[5],
                    "message": r[6],
                    "severity": r[7] or "WARNING",
                    "checked_at": r[8],
                    "origin": r[9]
                }
                for r in res
            ]

    def delete_manual_violations(self, filepath: str):
        """Clears manual violations for a file."""
        with self.db_conn.session() as conn:
            conn.execute(
                "DELETE FROM compliance_violations WHERE filepath = ? AND origin = 'manual'",
                (filepath,)
            )

    def delete_automatic_violations(self, rule_ids=None):
        """Deletes automatic violations, optionally filtered by rule IDs.
        
        Args:
            rule_ids: Optional list of rule IDs to filter. If None, deletes all automatic violations.
        """
        with self.db_conn.session() as conn:
            if rule_ids:
                placeholders = ",".join("?" for _ in rule_ids)
                conn.execute(
                    f"DELETE FROM compliance_violations WHERE origin = 'automatic' AND rule_id IN ({placeholders})",
                    rule_ids
                )
            else:
                conn.execute(
                    "DELETE FROM compliance_violations WHERE origin = 'automatic'"
                )

    def delete_automatic_violations_for_path(self, filepath_prefix: str):
        """Deletes automatic violations for files matching a path prefix.
        
        Args:
            filepath_prefix: Path prefix to filter violations (forward slashes normalized)
        """
        normalized_prefix = filepath_prefix.replace("\\", "/")
        with self.db_conn.session() as conn:
            conn.execute(
                "DELETE FROM compliance_violations WHERE replace(filepath, '\\', '/') LIKE ? AND origin = 'automatic'",
                (f"{normalized_prefix}%",)
            )

    def upsert_violations_bulk(self, violations):
        """Bulk upsert violations in a single transaction.
        
        Args:
            violations: List of dicts with keys: violation_id, rule_id, symbol, filepath, line, message, origin
        """
        if not violations:
            return
        with self.db_conn.session() as conn:
            for v in violations:
                conn.execute(
                    """
                    INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message, origin)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (violation_id) DO UPDATE SET
                        rule_id = excluded.rule_id,
                        symbol = excluded.symbol,
                        filepath = excluded.filepath,
                        line = excluded.line,
                        message = excluded.message,
                        origin = excluded.origin
                    """,
                    (
                        v["violation_id"],
                        v["rule_id"],
                        v.get("symbol"),
                        v["filepath"],
                        v["line"],
                        v["message"],
                        v.get("origin", "automatic")
                    )
                )
