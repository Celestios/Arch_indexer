import hashlib
from typing import Optional
from utils.session import resolve_filepath
from auditor.analyzer import Auditor


def handle_set_status(
    repository,
    project_root,
    filepath: str,
    status: str,
    justification: Optional[str] = None
) -> str:
    """Sets manual AI logical compliance status for a file."""
    status_upper = status.upper()
    if status_upper not in ("COMPLIANT", "VIOLATION_DETECTED"):
        return f"Error: Invalid manual compliance status choice: '{status}'. Allowed: COMPLIANT, VIOLATION_DETECTED."

    if status_upper == "VIOLATION_DETECTED" and not justification:
        return "Error: Justification must be provided when flagging a file as VIOLATION_DETECTED."

    resolved = resolve_filepath(repository, filepath)
    if not resolved:
        return f"Error: File '{filepath}' is not registered in the database."

    repository.files.update_file_manual_status(resolved, status_upper, justification)
    repository.compliance.delete_manual_violations(resolved)

    if status_upper == "VIOLATION_DETECTED":
        violation_text = f"manual_logical_audit_{resolved}_{justification}"
        violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]

        repository.compliance.add_violation(
            violation_id=violation_id,
            rule_id="logical_audit",
            symbol=None,
            filepath=resolved,
            line=1,
            message=justification,
            origin="manual"
        )

    try:
        auditor = Auditor(repository, project_root)
        auditor.run_audit()
    except Exception:
        pass

    return f"Successfully updated manual status for '{resolved}' to '{status_upper}'."
