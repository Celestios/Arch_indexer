import sys

from interface.tools.impact import handle_impact
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("impact", help="Perform blast radius / transitive dependency analysis for a symbol")
    p.add_argument("symbol", help="Target symbol name")
    p.add_argument("--max-depth", type=int, default=4, help="Maximum traversal depth (default: 4)")
    p.add_argument(
        "--direction",
        choices=["upstream", "downstream", "both"],
        default="upstream",
        help="Traversal direction (default: upstream)",
    )
    p.add_argument("--max-nodes", type=int, default=50, help="Maximum tree nodes per direction (default: 50)")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_impact)


def cmd_impact(args):
    """Performs blast radius analysis for a symbol or class."""
    with workspace_session(args) as (project_root, _, repository):
        try:
            print(
                handle_impact(
                    args.symbol,
                    getattr(args, "max_depth", 4),
                    repository,
                    direction=getattr(args, "direction", "upstream"),
                    max_nodes=getattr(args, "max_nodes", 50),
                    project_root=project_root,
                )
            )
        except Exception as e:
            print(f"Error computing blast radius: {e}", file=sys.stderr)
            sys.exit(1)
