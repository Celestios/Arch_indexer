from auditor.analyzer import Auditor
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("clear-pending", help="Clear all pending audit flags")
    p.add_argument("justification", help="Justification comment for clearing all pending audits")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_clear_pending)


def cmd_clear_pending(args):
    """Clears all pending audit flags in the database."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        repository.files.clear_all_pending_audits(args.justification)
        auditor = Auditor(repository, project_root)
        auditor.run_audit()
        print("Successfully cleared pending audit status for all files.")
