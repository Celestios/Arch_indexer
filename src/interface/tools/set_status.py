"""Shared handler for setting or clearing manual logical review status (Axis 3) on a file."""
from pathlib import Path
from typing import Optional, Tuple

from db.store_quality import VALID_SEVERITIES, normalize_severity
from utils.violation_id import generate_violation_id

VALID_MANUAL_STATUSES = ("COMPLIANT", "VIOLATION_DETECTED", "CLEAR")


def handle_set_status(
    repository,
    project_root: Path,
    filepath: str,
    status: str,
    justification: Optional[str] = None,
    category: str = "logical_audit",
    severity: str = "Warning",
    symbol: Optional[str] = None,
    line: int = 1,
) -> Tuple[str, bool]:
    """
    Updates manual logical review state (Axis 3) for a file and returns (message, ok).
    - COMPLIANT: marks manual_status='COMPLIANT', clears pending_audit=FALSE, removes manual violations.
    - VIOLATION_DETECTED: marks manual_status='VIOLATION_DETECTED', clears pending_audit=FALSE, records a manual finding.
    - CLEAR: resets manual_status=NULL and removes manual violations without altering pending_audit.
    Never modifies files.status (Axis 1) or automatic violations.
    """
    status_upper = (status or "").strip().upper()
    if status_upper not in VALID_MANUAL_STATUSES:
        return (
            f"Error: Invalid manual compliance status: '{status}'. Allowed: {', '.join(VALID_MANUAL_STATUSES)}.",
            False,
        )

    if status_upper == "VIOLATION_DETECTED" and not (justification and justification.strip()):
        return "Error: Justification must be provided when flagging a file as VIOLATION_DETECTED.", False

    sev_raw = (severity or "Warning").strip()
    if sev_raw.lower() not in {s.lower() for s in VALID_SEVERITIES}:
        return (
            f"Error: Invalid severity: '{severity}'. Allowed: {', '.join(VALID_SEVERITIES)}.",
            False,
        )
    sev_norm = normalize_severity(sev_raw)

    cat_clean = (category or "logical_audit").strip() or "logical_audit"
    try:
        line_num = max(1, int(line))
    except (TypeError, ValueError):
        return f"Error: Invalid line number: '{line}'. Must be an integer >= 1.", False

    resolved_fp = repository.workspace.resolve_filepath(filepath)
    if not resolved_fp:
        return f"Error: File '{filepath}' is not registered in the database.", False

    resolved_sym: Optional[str] = None
    if symbol and symbol.strip():
        rec = repository.graph.resolve_symbol(symbol.strip())
        resolved_sym = rec["symbol"] if rec else symbol.strip()
        if line == 1 and rec and rec.get("start_line"):
            line_num = int(rec["start_line"])

    with repository.transaction():
        repository.quality.delete_violations(filepath=resolved_fp, origin="manual")

        if status_upper == "CLEAR":
            repository.workspace.update_file_manual_status(
                resolved_fp,
                None,
                justification,
                clear_pending=False,
            )
            return f"Successfully cleared manual status for '{resolved_fp}'.", True

        repository.workspace.update_file_manual_status(
            resolved_fp,
            status_upper,
            justification,
            clear_pending=True,
        )

        if status_upper == "VIOLATION_DETECTED":
            violation_id = generate_violation_id("manual", cat_clean, resolved_fp, resolved_sym or "", justification)
            repository.quality.upsert_violation(
                violation_id=violation_id,
                rule_id=cat_clean,
                symbol=resolved_sym,
                filepath=resolved_fp,
                line=line_num,
                message=justification.strip(),
                origin="manual",
                severity=sev_norm,
            )

    if status_upper == "VIOLATION_DETECTED":
        return (
            f"Successfully flagged '{resolved_fp}' as 'VIOLATION_DETECTED' "
            f"[{cat_clean} | {sev_norm} | L{line_num}].",
            True,
        )
    return f"Successfully updated manual status for '{resolved_fp}' to '{status_upper}'.", True
