"""Shared handler for setting manual AI logical compliance status on a file."""
from pathlib import Path
from typing import Optional, Tuple

from auditor.analyzer import Auditor
from utils.helpers import resolve_filepath
from utils.violation_id import generate_violation_id


def handle_set_status(
    repository,
    project_root: Path,
    filepath: str,
    status: str,
    justification: Optional[str] = None,
    run_audit: bool = True,
) -> Tuple[str, bool]:
    """Sets manual compliance status for a file and returns (message, ok)."""
    status_upper = status.upper()
    if status_upper not in ("COMPLIANT", "VIOLATION_DETECTED"):
        return (
            f"Error: Invalid manual compliance status choice: '{status}'. Allowed: COMPLIANT, VIOLATION_DETECTED.",
            False,
        )

    if status_upper == "VIOLATION_DETECTED" and not justification:
        return "Error: Justification must be provided when flagging a file as VIOLATION_DETECTED.", False

    resolved = resolve_filepath(repository, filepath)
    if not resolved:
        return f"Error: File '{filepath}' is not registered in the database.", False

    repository.workspace.update_file_manual_status(resolved, status_upper, justification)
    repository.quality.delete_violations(filepath=resolved, origin="manual")

    if status_upper == "VIOLATION_DETECTED":
        violation_id = generate_violation_id("manual_logical_audit", resolved, justification)
        repository.quality.upsert_violation(
            violation_id=violation_id,
            rule_id="logical_audit",
            symbol=None,
            filepath=resolved,
            line=1,
            message=justification,
            origin="manual",
        )

    if run_audit:
        try:
            Auditor(repository, project_root).run_audit()
        except Exception:
            pass

    return f"Successfully updated manual status for '{resolved}' to '{status_upper}'.", True
