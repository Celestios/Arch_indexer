import argparse
import os
import sys
from pathlib import Path

from utils.session import get_project_root
from utils.helpers import CONFIG_DIR_NAME


def register(subparsers):
    p = subparsers.add_parser("mcp", help="Start and manage the MCP server")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--port", type=int, default=0, help="Port for SSE transport (default: auto/8071)")
    p.add_argument("--stop", action="store_true", help="Stop the running MCP server instance")
    p.add_argument("--restart", action="store_true", help="Restart the MCP server (stops existing instance first)")
    p.add_argument("--status", action="store_true", help="Check status of the running MCP server")
    p.add_argument("--headless", action="store_true", help="Run the server headlessly in background and print status")
    p.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_mcp)


def cmd_mcp(args):
    """Manages and starts the FastMCP server."""
    project_root = get_project_root(args)
    os.environ["ARCH_PROJECT_ROOT"] = str(project_root)

    arch_dir = project_root / CONFIG_DIR_NAME
    req_port = getattr(args, "port", 0)

    from utils.single_instance import (
        acquire_server,
        get_server_status,
        read_lock,
        start_headless,
        stop_server,
    )

    # 1. Handle --stop
    if getattr(args, "stop", False):
        stopped_pid = stop_server(arch_dir)
        if stopped_pid:
            print(f"[Arch MCP] Stopped server (PID {stopped_pid}).")
        else:
            print("[Arch MCP] No running server found.")
        sys.exit(0)

    # 2. Handle --status
    if getattr(args, "status", False):
        status = get_server_status(arch_dir)
        if status and status.get("healthy"):
            print("[Arch MCP] Server is running:")
            print(f"  URL:     {status['url']}")
            print(f"  PID:     {status['pid']}")
            print(f"  Port:    {status['port']}")
            print("  Status:  Healthy")
        elif status:
            print("[Arch MCP] Server process exists but is unresponsive:")
            print(f"  URL:     {status['url']}")
            print(f"  PID:     {status['pid']}")
            print("  Status:  Unresponsive")
        else:
            print("[Arch MCP] Server is not running.")
        sys.exit(0)

    # 3. Handle --restart
    if getattr(args, "restart", False):
        stopped_pid = stop_server(arch_dir)
        if stopped_pid:
            print(f"[Arch MCP] Stopped existing server (PID {stopped_pid}).")

    # 4. Handle --headless
    if getattr(args, "headless", False):
        existing = get_server_status(arch_dir)
        if existing and existing.get("healthy"):
            print("[Arch MCP] Server is already running:")
            print(f"  URL:     {existing['url']}")
            print(f"  PID:     {existing['pid']}")
            print("  Status:  Healthy")
            print("\nOptions:")
            print("  - Stop server:            python src/main.py mcp --stop")
            print("  - Restart headlessly:     python src/main.py mcp --restart --headless")
            sys.exit(0)

        print("[Arch MCP] Starting server headlessly in background...")
        info = start_headless(project_root, port=req_port)
        if info and info.get("healthy"):
            print("[Arch MCP] Server started successfully:")
            print(f"  URL:     {info['url']}")
            print(f"  PID:     {info['pid']}")
            print(f"  Logs:    .arch/mcp.log")
            print("  Status:  Healthy")
            print("\nTo stop it:    python src/main.py mcp --stop")
            sys.exit(0)
        else:
            print("[Arch MCP] Failed to start server headlessly. Check .arch/mcp.log for details.", file=sys.stderr)
            sys.exit(1)

    # 5. Foreground mode (default or internal child)
    is_foreground_worker = getattr(args, "foreground", False)
    if not is_foreground_worker:
        existing = get_server_status(arch_dir)
        if existing and existing.get("healthy"):
            print("[Arch MCP] Server is already running:")
            print(f"  URL:     {existing['url']}")
            print(f"  PID:     {existing['pid']}")
            print("  Status:  Healthy")
            print("\nOptions:")
            print("  - Stop server:            python src/main.py mcp --stop")
            print("  - Restart in foreground:  python src/main.py mcp --restart")
            print("  - Restart headlessly:     python src/main.py mcp --restart --headless")
            sys.exit(0)

    existing_url = acquire_server(arch_dir, port=req_port)
    if existing_url and not is_foreground_worker:
        print(f"[Arch MCP] Server already running at {existing_url}")
        sys.exit(0)

    # Ensure src is in sys.path
    src_dir = Path(__file__).resolve().parent.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    lock = read_lock(arch_dir)
    port = lock.get("port", 0) if lock else req_port
    url = f"http://127.0.0.1:{port}" if port > 0 else "stdio"

    print("[Arch MCP] Starting server in foreground...")
    print(f"  URL:       {url}")
    print(f"  PID:       {os.getpid()}")
    print(f"  Transport: {'SSE' if port > 0 else 'stdio'}")
    print("  Tools:     lookup, context, impact, audit, compile_context, map, reindex, set_status")
    print("Press Ctrl+C to terminate.\n", flush=True)

    from interface.server import run_server
    run_server(port=port)

