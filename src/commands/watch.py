import sys

from change_tracker.watcher import start_watcher
from utils.session import get_project_root


def cmd_watch(args):
    """Watches the project root for file changes and auto-indexes/audits."""
    project_root = get_project_root(args)
    debounce = args.debounce
    try:
        start_watcher(project_root, debounce)
    except Exception as e:
        print(f"Watcher error: {e}", file=sys.stderr)
        sys.exit(1)
