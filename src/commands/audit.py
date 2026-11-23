from interface.tools.audit import handle_audit
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("audit", help="Run compliance audit with compact scorecard rollup")
    p.add_argument(
        "--summary-only",
        action="store_true",
        help="Show only the compliance scorecard and hotspot files without individual violation traces",
    )
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_audit)


def cmd_audit(args):
    """Run architectural compliance audit."""
    with workspace_session(args) as (project_root, _, repository):
        print(handle_audit(repository, project_root, summary_only=getattr(args, "summary_only", False)))
