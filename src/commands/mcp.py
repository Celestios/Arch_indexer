import argparse
import os
import sys
from pathlib import Path

from utils.session import get_project_root


def register(subparsers):
    p = subparsers.add_parser("mcp", help="Start and manage the MCP daemon")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--port", type=int, default=0, help="Port for SSE transport (default: 8071)")
    p.add_argument("--stop", action="store_true", help="Stop the running MCP daemon")
    p.add_argument("--restart", action="store_true", help="Restart the MCP daemon")
    p.add_argument("--status", action="store_true", help="Check status of the running MCP daemon")
    p.add_argument("--headless", action="store_true", help="Run the daemon headlessly in background")
    p.add_argument("--stdio", action="store_true", help="Run MCP server in STDIO mode for IDE clients")
    p.add_argument("--foreground", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_mcp)


def cmd_mcp(args):
    """Manages and starts the machine-global FastMCP daemon."""
    project_root = get_project_root(args)
    passed_root = getattr(args, "project_root", None)
    if (project_root / ".arch" / "arch.db").exists() or (passed_root and passed_root != "."):
        os.environ["ARCH_PROJECT_ROOT"] = str(project_root)
    elif "ARCH_PROJECT_ROOT" in os.environ and not (Path(os.environ["ARCH_PROJECT_ROOT"]) / ".arch" / "arch.db").exists():
        del os.environ["ARCH_PROJECT_ROOT"]

    req_port = getattr(args, "port", 0)

    from utils.single_instance import (
        acquire_server,
        get_global_arch_dir,
        get_server_status,
        read_lock,
        register_workspace,
        start_headless,
        stop_server,
    )

    global_arch_dir = get_global_arch_dir()
    cmd_prefix = "arch" if getattr(sys, "frozen", False) else "python src/main.py"

    # Handle --stdio mode for IDEs (Antigravity, Cursor, etc.)
    if getattr(args, "stdio", False):
        if passed_root and passed_root != ".":
            try:
                register_workspace(project_root, global_arch_dir)
            except Exception:
                pass
        from interface.server import run_server
        run_server(port=0)
        sys.exit(0)

    # 1. Handle --stop
    if getattr(args, "stop", False):
        stopped_pid = stop_server(global_arch_dir)
        if stopped_pid:
            print(f"[Arch MCP] Stopped server (PID {stopped_pid}).")
        else:
            print("[Arch MCP] No running server found.")
        sys.exit(0)

    # 2. Handle --status
    if getattr(args, "status", False):
        status = get_server_status(global_arch_dir)
        if status and status.get("healthy"):
            print("[Arch MCP] Server is running:")
            print(f"  URL:     {status['url']}")
            print(f"  PID:     {status['pid']}")
            print(f"  Port:    {status['port']}")
            print("  Status:  Healthy")
            try:
                from interface.project_registry import ProjectRegistry
                reg = ProjectRegistry.get_instance(global_dir=global_arch_dir)
                projs = reg.list_projects()
                if projs:
                    print(f"\nRegistered Workspaces ({len(projs)}):")
                    for p in projs:
                        marker = " (active)" if p["is_active"] else ""
                        print(f"  - {p['name']}: {p['root']}{marker}")
            except Exception:
                pass
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
        stopped_pid = stop_server(global_arch_dir)
        if stopped_pid:
            print(f"[Arch MCP] Stopped existing server (PID {stopped_pid}).")

    # 4. Handle --headless
    if getattr(args, "headless", False):
        existing = get_server_status(global_arch_dir)
        if existing and existing.get("healthy"):
            try:
                register_workspace(project_root, global_arch_dir)
            except Exception:
                pass
            print("[Arch MCP] Server is already running:")
            print(f"  URL:     {existing['url']}")
            print(f"  PID:     {existing['pid']}")
            print("  Status:  Healthy")
            print(f"  Registered workspace: {project_root}")
            print("\nOptions:")
            print(f"  - Stop server:            {cmd_prefix} mcp --stop")
            print(f"  - Restart headlessly:     {cmd_prefix} mcp --restart --headless")
            sys.exit(0)

        print("[Arch MCP] Starting server headlessly in background...")
        info = start_headless(project_root, port=req_port)
        if info and info.get("healthy"):
            print("[Arch MCP] Server started successfully:")
            print(f"  URL:     {info['url']}")
            print(f"  PID:     {info['pid']}")
            print(f"  Logs:    ~/.arch/daemon.log")
            print("  Status:  Healthy")
            print(f"\nTo stop it:    {cmd_prefix} mcp --stop")
            sys.exit(0)
        else:
            print("[Arch MCP] Failed to start server headlessly. Check ~/.arch/daemon.log for details.", file=sys.stderr)
            sys.exit(1)

    # 5. Foreground mode (default or internal child)
    is_foreground_worker = getattr(args, "foreground", False)
    if not is_foreground_worker:
        existing = get_server_status(global_arch_dir)
        if existing and existing.get("healthy"):
            try:
                register_workspace(project_root, global_arch_dir)
            except Exception:
                pass
            print("[Arch MCP] Server is already running:")
            print(f"  URL:     {existing['url']}")
            print(f"  PID:     {existing['pid']}")
            print("  Status:  Healthy")
            print(f"  Registered workspace: {project_root}")
            print("\nOptions:")
            print(f"  - Stop server:            {cmd_prefix} mcp --stop")
            print(f"  - Restart in foreground:  {cmd_prefix} mcp --restart")
            print(f"  - Restart headlessly:     {cmd_prefix} mcp --restart --headless")
            sys.exit(0)

    existing_url = acquire_server(global_arch_dir, port=req_port)
    if existing_url and not is_foreground_worker:
        print(f"[Arch MCP] Server already running at {existing_url}")
        sys.exit(0)

    try:
        register_workspace(project_root, global_arch_dir)
    except Exception:
        pass

    # Ensure src is in sys.path
    src_dir = Path(__file__).resolve().parent.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    lock = read_lock(global_arch_dir)
    port = lock.get("port", 0) if lock else req_port
    url = f"http://127.0.0.1:{port}" if port > 0 else "stdio"

    # In stdio mode, stdout is strictly reserved for JSON-RPC messages
    out_dest = sys.stderr if port <= 0 else sys.stdout

    print("[Arch MCP] Starting server in foreground...", file=out_dest)
    print(f"  URL:       {url}", file=out_dest)
    print(f"  PID:       {os.getpid()}", file=out_dest)
    print(f"  Transport: {'SSE' if port > 0 else 'stdio'}", file=out_dest)
    print("  Tools:     lookup, context, impact, audit, compile_context, map, update, set_status, projects, register_project", file=out_dest)
    print("Press Ctrl+C to terminate.\n", file=out_dest, flush=True)

    from interface.server import run_server
    run_server(port=port)
