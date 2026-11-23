"""CLI command for parameter-free hierarchical clustering analysis."""
import sys

from interface.tools.clusters import handle_clusters
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser(
        "clusters",
        help="Hierarchical graph clustering, containment scoring, and architectural drift diagnostics",
    )
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--cluster", default=None, help="Cluster ID or target symbol/filepath to inspect")
    p.add_argument("--depth", type=int, default=2, help="Hierarchy expansion depth (default: 2)")
    p.add_argument("--unit", choices=["symbol", "file"], default="symbol", help="Unit of analysis (default: symbol)")
    p.add_argument("--view", choices=["both", "tree", "mermaid"], default="both", help="Output view (default: both)")
    p.add_argument("--scope", default=None, help="Comma-separated directory prefix scope filter")
    p.add_argument("--language", default=None, help="Language filter")
    p.add_argument("--include-tests", action="store_true", default=False, help="Include test files and symbols")
    p.add_argument("--no-drift", dest="include_drift", action="store_false", default=True, help="Disable drift diagnostics")
    p.set_defaults(func=cmd_clusters)


def cmd_clusters(args):
    """Runs hierarchical clustering analysis."""
    with workspace_session(args) as (project_root, _, repository):
        try:
            scope = [s.strip() for s in args.scope.split(",") if s.strip()] if args.scope else None
            print(
                handle_clusters(
                    repository=repository,
                    project_root=project_root,
                    cluster=args.cluster,
                    depth=args.depth,
                    unit=args.unit,
                    view=args.view,
                    scope=scope,
                    language=args.language,
                    include_tests=args.include_tests,
                    include_drift=args.include_drift,
                )
            )
        except Exception as e:
            print(f"Error running cluster analysis: {e}", file=sys.stderr)
            sys.exit(1)
