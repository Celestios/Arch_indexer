from typing import Dict, List, Any, Optional
from db.base import BaseRepository

class ComplianceRepository(BaseRepository):
    """
    Handles queries and updates to compliance rules and violations tables.
    """

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
