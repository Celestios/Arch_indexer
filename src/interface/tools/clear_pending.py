"""Shared handler for clearing all pending_audit review flags (Axis 2)."""
from pathlib import Path


def handle_clear_pending(repository, project_root: Path, justification: str) -> str:
    """Clears the pending_audit flag on all files without touching automatic rules or manual_status."""
    repository.workspace.update_clear_pending_audits(justification)
    return "Successfully cleared pending review status for all files."
