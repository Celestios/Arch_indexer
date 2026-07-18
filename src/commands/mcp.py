import os
import sys
from pathlib import Path

from utils.session import get_project_root


def cmd_mcp(args):
    """Starts the FastMCP server."""
    project_root = get_project_root(args)
    os.environ["ARCH_PROJECT_ROOT"] = str(project_root)

    # We must ensure that the path to src is in sys.path
    src_dir = Path(__file__).resolve().parent.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from interface.server import run_server
    run_server()
