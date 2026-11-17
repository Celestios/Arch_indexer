"""Single-instance management for the MCP server.

First instance starts the server and writes connection info to .arch/arch.lock.
Second instance reads the lock, verifies the server is alive, and returns the URL.
"""
import atexit
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

CONFIG_DIR_NAME = ".arch"
LOCK_FILE_NAME = "arch.lock"
DEFAULT_PORT = 8071


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _server_alive(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _find_open_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 100):
        if not _port_open(port):
            return port
    raise RuntimeError(f"No open port found in range {start}-{start + 99}")


def read_lock(arch_dir: Path) -> Optional[dict]:
    lock_path = arch_dir / LOCK_FILE_NAME
    if not lock_path.exists():
        return None
    try:
        data = json.loads(lock_path.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        return None


def check_existing(arch_dir: Path) -> Optional[str]:
    """Check if a server is already running and responding.

    Returns the server URL if alive, None otherwise. Cleans up stale locks.
    """
    lock = read_lock(arch_dir)
    if not lock:
        return None

    pid = lock.get("pid")
    url = lock.get("url")

    if not pid or not url:
        arch_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        return None

    if not _pid_alive(pid):
        arch_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        return None

    if _server_alive(url):
        return url

    # PID exists but server not responding — stale
    arch_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
    return None


def write_lock(arch_dir: Path, pid: int, port: int) -> Path:
    arch_dir.mkdir(parents=True, exist_ok=True)
    lock_path = arch_dir / LOCK_FILE_NAME
    data = {"pid": pid, "port": port, "url": f"http://127.0.0.1:{port}"}
    lock_path.write_text(json.dumps(data))
    return lock_path


def acquire_server(arch_dir: Path, port: int = 0) -> Optional[str]:
    """Try to acquire a server slot.

    If a server is already running, returns its URL.
    If not, writes a new lock file with our PID and returns None (caller should start server).
    """
    existing = check_existing(arch_dir)
    if existing:
        return existing

    if port <= 0:
        port = _find_open_port()
    write_lock(arch_dir, os.getpid(), port)

    def cleanup():
        lock_path = arch_dir / LOCK_FILE_NAME
        try:
            data = json.loads(lock_path.read_text())
            if data.get("pid") == os.getpid():
                lock_path.unlink(missing_ok=True)
        except Exception:
            lock_path.unlink(missing_ok=True)

    atexit.register(cleanup)
    return None


def _kill_pid(pid: int) -> bool:
    """Terminates a process by PID across Windows and Unix."""
    if sys.platform == "win32":
        try:
            PROCESS_TERMINATE = 0x0001
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if handle:
                kernel32.TerminateProcess(handle, 0)
                kernel32.CloseHandle(handle)
                return True
        except Exception:
            pass
        try:
            res = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False
    else:
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


def stop_server(arch_dir: Path) -> Optional[int]:
    """Stops the running MCP server if active.

    Returns the PID of the stopped server, or None if no running server was found.
    """
    lock = read_lock(arch_dir)
    if not lock:
        return None

    pid = lock.get("pid")
    if not pid:
        arch_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        return None

    if _pid_alive(pid):
        _kill_pid(pid)
        time.sleep(0.2)

    arch_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
    return pid


def get_server_status(arch_dir: Path) -> Optional[dict]:
    """Retrieves live server status if active and verified."""
    lock = read_lock(arch_dir)
    if not lock:
        return None

    pid = lock.get("pid")
    url = lock.get("url")
    port = lock.get("port", DEFAULT_PORT)

    if not pid or not _pid_alive(pid):
        arch_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        return None

    healthy = _server_alive(url) if url else False
    return {
        "pid": pid,
        "port": port,
        "url": url or f"http://127.0.0.1:{port}",
        "healthy": healthy,
    }


def start_headless(project_root: Path, port: int = 0) -> Optional[dict]:
    """Starts the MCP server headlessly in a detached background process.

    Waits for the server to initialize and returns status dict, or None on failure.
    """
    arch_dir = project_root / CONFIG_DIR_NAME
    arch_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = arch_dir / "mcp.log"

    if port <= 0:
        port = _find_open_port()

    main_script = Path(__file__).resolve().parent.parent / "main.py"
    cmd = [
        sys.executable,
        str(main_script),
        "mcp",
        str(project_root),
        "--port",
        str(port),
        "--foreground",
    ]

    log_file = open(log_file_path, "a", encoding="utf-8")

    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | 0x00000008  # DETACHED_PROCESS
            | 0x08000000  # CREATE_NO_WINDOW
        )
    else:
        start_new_session = True

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
            close_fds=True,
        )
    finally:
        log_file.close()

    start_time = time.time()
    while time.time() - start_time < 5.0:
        time.sleep(0.2)
        status = get_server_status(arch_dir)
        if status and status.get("healthy"):
            return status

    # Check if process crashed immediately
    if proc.poll() is not None:
        return None

    return get_server_status(arch_dir)

