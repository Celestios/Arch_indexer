"""Single-instance management for the MCP server.

First instance starts the server and writes connection info to .arch/arch.lock.
Second instance reads the lock, verifies the server is alive, and returns the URL.
"""
import atexit
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

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
