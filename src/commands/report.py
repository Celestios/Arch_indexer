import sys

from interface.tools.report import handle_report
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("report", help="Generate workspace data reports")
    p.add_argument("name", choices=["overview", "compliance"], help="Report name")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_report)


def cmd_report(args):
    """Generates a codebase report."""
    with workspace_session(args) as (_, _, repository):
        try:
            print(handle_report(repository, args.name, args.format))
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
