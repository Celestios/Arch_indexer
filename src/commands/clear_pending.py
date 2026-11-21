from interface.tools.clear_pending import handle_clear_pending
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("clear-pending", help="Clear all pending audit flags")
    p.add_argument("justification", help="Justification comment for clearing all pending audits")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_clear_pending)


def cmd_clear_pending(args):
    """Clears all pending audit flags in the database."""
    with workspace_session(args) as (project_root, _, repository):
        print(handle_clear_pending(repository, project_root, args.justification))
