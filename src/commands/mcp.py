import os
import sys
from pathlib import Path

from utils.session import get_project_root
from utils.helpers import CONFIG_DIR_NAME


def register(subparsers):
    p = subparsers.add_parser("mcp", help="Start the MCP server")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--port", type=int, default=0, help="Port for SSE transport (default: stdio)")
    p.set_defaults(func=cmd_mcp)


def cmd_mcp(args):
    """Starts the FastMCP server."""
    project_root = get_project_root(args)
    os.environ["ARCH_PROJECT_ROOT"] = str(project_root)

    # Single-instance check — return existing server URL if running
    from utils.single_instance import acquire_server
    arch_dir = project_root / CONFIG_DIR_NAME
    req_port = getattr(args, "port", 0)
    existing_url = acquire_server(arch_dir, port=req_port)
    if existing_url:
        print(existing_url)
        sys.exit(0)

    # We must ensure that the path to src is in sys.path
    src_dir = Path(__file__).resolve().parent.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from utils.single_instance import read_lock
    lock = read_lock(arch_dir)
    port = lock.get("port", 0) if lock else req_port

    from interface.server import run_server
    run_server(port=port)
