import sys

from db.store_quality import VALID_SEVERITIES
from interface.tools.set_status import VALID_MANUAL_STATUSES, handle_set_status
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("set-status", help="Set or clear manual AI logical compliance status for a file")
    p.add_argument("filepath", help="Filepath to the target file")
    p.add_argument(
        "status",
        choices=list(VALID_MANUAL_STATUSES),
        help="Manual logical compliance status (COMPLIANT, VIOLATION_DETECTED, or CLEAR)",
    )
    p.add_argument("justification", nargs="?", default=None, help="Justification comment (required for VIOLATION_DETECTED)")
    p.add_argument("--category", default="logical_audit", help="Violation category / rule_id (default: logical_audit)")
    p.add_argument(
        "--severity",
        choices=list(VALID_SEVERITIES),
        default="Warning",
        help="Finding severity (default: Warning)",
    )
    p.add_argument("--symbol", default=None, help="Optional target symbol within the file")
    p.add_argument("--line", type=int, default=1, help="Line number for the finding (default: 1)")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_set_status)


def cmd_set_status(args):
    """Sets or clears manual AI compliance status for a file."""
    with workspace_session(args) as (project_root, _, repository):
        msg, ok = handle_set_status(
            repository,
            project_root,
            args.filepath,
            args.status,
            args.justification,
            category=getattr(args, "category", "logical_audit"),
            severity=getattr(args, "severity", "Warning"),
            symbol=getattr(args, "symbol", None),
            line=getattr(args, "line", 1),
        )
        if not ok:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(msg)
