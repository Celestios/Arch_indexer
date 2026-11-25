from interface.tools.update import handle_update
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("update", help="Synchronize workspace symbols, call graph, and audit state")
    p.add_argument(
        "--force",
        action="store_true",
        help="Delete cached SCIP indexes and force a full rebuild",
    )
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_update)


def cmd_update(args):
    """Synchronize workspace symbols, call graph edges, and architectural audit state."""
    with workspace_session(args) as (project_root, _, repository):
        print(handle_update(repository, project_root, force=getattr(args, "force", False)))
