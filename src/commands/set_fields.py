import sys

from interface.tools.set_fields import handle_set_fields
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("set-fields", help="Set manual metadata fields for a file")
    p.add_argument("filepath", help="Filepath to the target file")
    p.add_argument("fields_json", help="JSON string of fields to update")
    p.add_argument("justification", nargs="?", default=None, help="Optional update justification")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_set_fields)


def cmd_set_fields(args):
    """Sets manual fields for a file."""
    with workspace_session(args) as (project_root, _, repository):
        msg, ok = handle_set_fields(repository, project_root, args.filepath, args.fields_json, args.justification)
        if not ok:
            print(msg, file=sys.stderr)
            sys.exit(1)
        print(msg)
