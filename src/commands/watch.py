import sys

from change_tracker.watcher import start_watcher
from utils.session import get_project_root


def register(subparsers):
    p = subparsers.add_parser("watch", help="Watch workspace and auto-index and audit on changes")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--debounce", type=float, default=3.0, help="Debounce delay in seconds")
    p.set_defaults(func=cmd_watch)


def cmd_watch(args):
    """Watches the project root for file changes and auto-indexes/audits."""
    project_root = get_project_root(args)
    debounce = args.debounce
    try:
        start_watcher(project_root, debounce)
    except Exception as e:
        print(f"Watcher error: {e}", file=sys.stderr)
        sys.exit(1)
