from auditor.analyzer import Auditor


def handle_clear_pending_audits(repository, project_root) -> str:
    """Clear pending audit flags for all files. Returns markdown."""
    repository.files.clear_all_pending_audits("Cleared manually via API")
    auditor = Auditor(repository, project_root)
    auditor.run_audit()
    return "Successfully cleared pending audit status for all files."
