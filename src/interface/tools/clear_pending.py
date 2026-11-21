"""Shared handler for clearing all pending audit flags."""
from pathlib import Path

from auditor.analyzer import Auditor


def handle_clear_pending(repository, project_root: Path, justification: str) -> str:
    """Clears all pending audit flags in the database and re-runs the audit."""
    repository.workspace.update_clear_pending_audits(justification)
    Auditor(repository, project_root).run_audit()
    return "Successfully cleared pending audit status for all files."
