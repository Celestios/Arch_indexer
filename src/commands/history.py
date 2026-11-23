import sys

from interface.tools.history import handle_history
from interface.validators import VALID_HISTORY_SECTIONS
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser(
        "history",
        help="Run on-the-fly Git evolution, hotspot, thrash, coupling, growth, test-gap, or archaeology analysis",
    )
    p.add_argument(
        "--sections",
        default=None,
        help=f"Comma-separated sections ({', '.join(VALID_HISTORY_SECTIONS)}). Default: hotspots,coupling (or archaeology,coupling with --target)",
    )
    p.add_argument("--target", default=None, help="Target file path or symbol identifier")
    p.add_argument("--scope", default=None, help="Comma-separated directory prefix scope filter")
    p.add_argument("--commits", type=int, default=100, help="Number of recent non-merge commits to analyze (default: 100)")
    p.add_argument("--limit", type=int, default=10, help="Maximum items returned per section (default: 10)")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_history)


def cmd_history(args):
    """Runs composable Git evolution analysis."""
    with workspace_session(args) as (project_root, _, repository):
        try:
            scope = [s.strip() for s in args.scope.split(",") if s.strip()] if args.scope else None
            print(
                handle_history(
                    repository=repository,
                    project_root=project_root,
                    sections=args.sections,
                    target=args.target,
                    scope=scope,
                    commits=args.commits,
                    limit=args.limit,
                )
            )
        except Exception as e:
            print(f"Error running history analysis: {e}", file=sys.stderr)
            sys.exit(1)
