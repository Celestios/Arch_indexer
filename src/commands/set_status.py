import sys

from interface.tools.set_status import handle_set_status
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("set-status", help="Set manual AI logical compliance status for a file")
    p.add_argument("filepath", help="Filepath to the target file")
    p.add_argument("status", choices=["COMPLIANT", "VIOLATION_DETECTED"], help="Manual logical compliance status")
    p.add_argument("justification", nargs="?", default=None, help="Justification comment (required for VIOLATION_DETECTED)")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_set_status)


def cmd_set_status(args):
    """Sets manual AI compliance status flag for a file."""
    with workspace_session(args) as (project_root, _, repository):
        msg, ok = handle_set_status(
            repository, project_root, args.filepath, args.status, args.justification, run_audit=False
        )
        if not ok:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(msg)
