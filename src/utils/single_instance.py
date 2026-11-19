"""Single-instance management for the machine-global MCP daemon.

First instance starts the daemon and writes connection info to ~/.arch/daemon.lock
and acquires a machine-global named mutex on Windows.
Subsequent instances detect the running daemon, register their workspace, and exit.
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
from typing import Optional, Dict, Any

if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

CONFIG_DIR_NAME = ".arch"
LOCK_FILE_NAME = "daemon.lock"
LEGACY_LOCK_FILE_NAME = "arch.lock"
PROJECTS_FILE_NAME = "projects.json"
DEFAULT_PORT = 8071
WINDOWS_MUTEX_NAME = "Local\\ArchMcpDaemonMutex"

_daemon_mutex_handle = None


def get_global_arch_dir() -> Path:
    """Returns the global machine configuration directory (~/.arch or ARCH_GLOBAL_DIR)."""
    if "ARCH_GLOBAL_DIR" in os.environ:
        return Path(os.environ["ARCH_GLOBAL_DIR"]).resolve()
    return (Path.home() / CONFIG_DIR_NAME).resolve()


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


def acquire_named_mutex() -> bool:
    """Acquires the machine-wide named mutex on Windows.

    Returns True if successfully acquired/created, False if already held by another process.
    On non-Windows platforms, returns True.
    """
    global _daemon_mutex_handle
    if sys.platform == "win32":
        ERROR_ALREADY_EXISTS = 183
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, WINDOWS_MUTEX_NAME)
        last_err = kernel32.GetLastError()
        if not handle:
            return False
        if last_err == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _daemon_mutex_handle = handle
        return True
    return True


def release_named_mutex():
    """Releases the machine-wide named mutex on Windows."""
    global _daemon_mutex_handle
    if sys.platform == "win32" and _daemon_mutex_handle:
        try:
            kernel32.CloseHandle(_daemon_mutex_handle)
        except Exception:
            pass
        _daemon_mutex_handle = None


atexit.register(release_named_mutex)


def read_lock(arch_dir: Optional[Path] = None) -> Optional[dict]:
    target_dir = arch_dir if arch_dir is not None else get_global_arch_dir()
    lock_path = target_dir / LOCK_FILE_NAME
    if not lock_path.exists():
        legacy_path = target_dir / LEGACY_LOCK_FILE_NAME
        if legacy_path.exists():
            lock_path = legacy_path
        else:
            return None
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return None


def write_lock(arch_dir: Optional[Path], pid: int, port: int) -> Path:
    target_dir = arch_dir if arch_dir is not None else get_global_arch_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    lock_path = target_dir / LOCK_FILE_NAME
    data = {"pid": pid, "port": port, "url": f"http://127.0.0.1:{port}"}
    lock_path.write_text(json.dumps(data), encoding="utf-8")
    return lock_path


def check_existing(arch_dir: Optional[Path] = None) -> Optional[str]:
    """Check if a daemon is already running and responding.

    Returns the server URL if alive, None otherwise. Cleans up stale locks.
    """
    target_dir = arch_dir if arch_dir is not None else get_global_arch_dir()
    lock = read_lock(target_dir)
    if not lock:
        return None

    pid = lock.get("pid")
    url = lock.get("url")

    def _cleanup():
        target_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        target_dir.joinpath(LEGACY_LOCK_FILE_NAME).unlink(missing_ok=True)
        release_named_mutex()

    if not pid or not url:
        _cleanup()
        return None

    if not _pid_alive(pid):
        _cleanup()
        return None

    if _server_alive(url):
        return url

    # PID exists but server not responding — stale
    _cleanup()
    return None


def acquire_server(arch_dir: Optional[Path] = None, port: int = 0) -> Optional[str]:
    """Try to acquire the daemon slot.

    If a daemon is already running, returns its URL.
    If not, writes lock file with our PID, acquires Windows mutex, and returns None.
    """
    target_dir = arch_dir if arch_dir is not None else get_global_arch_dir()
    existing = check_existing(target_dir)
    if existing:
        return existing

    # Try acquiring named mutex on Windows
    if not acquire_named_mutex():
        # Mutex held by another process starting up; wait briefly and check again
        time.sleep(0.3)
        existing = check_existing(target_dir)
        if existing:
            return existing

    if port <= 0:
        port = DEFAULT_PORT if not _port_open(DEFAULT_PORT) else _find_open_port(DEFAULT_PORT)

    write_lock(target_dir, os.getpid(), port)

    def cleanup():
        lock_path = target_dir / LOCK_FILE_NAME
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            if data.get("pid") == os.getpid():
                lock_path.unlink(missing_ok=True)
        except Exception:
            lock_path.unlink(missing_ok=True)
        release_named_mutex()

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


def stop_server(arch_dir: Optional[Path] = None) -> Optional[int]:
    """Stops the running MCP daemon if active.

    Returns the PID of the stopped server, or None if no running server was found.
    """
    target_dir = arch_dir if arch_dir is not None else get_global_arch_dir()
    lock = read_lock(target_dir)
    if not lock:
        return None

    pid = lock.get("pid")
    if not pid:
        target_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        target_dir.joinpath(LEGACY_LOCK_FILE_NAME).unlink(missing_ok=True)
        release_named_mutex()
        return None

    if _pid_alive(pid):
        _kill_pid(pid)
        time.sleep(0.2)

    target_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
    target_dir.joinpath(LEGACY_LOCK_FILE_NAME).unlink(missing_ok=True)
    release_named_mutex()
    return pid


def get_server_status(arch_dir: Optional[Path] = None) -> Optional[dict]:
    """Retrieves live daemon status if active and verified."""
    target_dir = arch_dir if arch_dir is not None else get_global_arch_dir()
    lock = read_lock(target_dir)
    if not lock:
        return None

    pid = lock.get("pid")
    url = lock.get("url")
    port = lock.get("port", DEFAULT_PORT)

    if not pid or not _pid_alive(pid):
        target_dir.joinpath(LOCK_FILE_NAME).unlink(missing_ok=True)
        target_dir.joinpath(LEGACY_LOCK_FILE_NAME).unlink(missing_ok=True)
        release_named_mutex()
        return None

    healthy = _server_alive(url) if url else False
    return {
        "pid": pid,
        "port": port,
        "url": url or f"http://127.0.0.1:{port}",
        "healthy": healthy,
    }


def register_workspace(project_root: Path, global_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Registers a workspace root in ~/.arch/projects.json."""
    target_dir = global_dir if global_dir is not None else get_global_arch_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    reg_file = target_dir / PROJECTS_FILE_NAME

    data: Dict[str, Any] = {"projects": {}, "active_project": None}
    if reg_file.exists():
        try:
            data = json.loads(reg_file.read_text(encoding="utf-8"))
        except Exception:
            data = {"projects": {}, "active_project": None}

    resolved_root = project_root.resolve()
    # Walk up to find project root containing .arch/arch.db
    cur = resolved_root if resolved_root.is_dir() else resolved_root.parent
    db_root = None
    while True:
        if (cur / ".arch" / "arch.db").exists():
            db_root = cur
            break
        if cur.parent == cur:
            break
        cur = cur.parent

    if not db_root:
        return data

    resolved_root = db_root
    root_str = str(resolved_root).replace("\\", "/")
    root_lower = root_str.lower()
    is_global = (target_dir.resolve() == get_global_arch_dir().resolve())
    if is_global and ("pytest" in root_lower or "temp" in root_lower or "tmp" in resolved_root.name.lower()):
        return data

    projects = data.setdefault("projects", {})
    now = time.time()
    projects[root_str] = {
        "name": resolved_root.name,
        "registered_at": projects.get(root_str, {}).get("registered_at", now),
        "last_accessed": now,
    }
    curr_active = data.get("active_project")
    if not curr_active or not (Path(curr_active) / ".arch" / "arch.db").exists():
        data["active_project"] = root_str

    reg_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def start_headless(project_root: Optional[Path] = None, port: int = 0) -> Optional[dict]:
    """Starts the MCP daemon headlessly in a detached background process."""
    global_dir = get_global_arch_dir()
    global_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = global_dir / "daemon.log"

    resolved_root = (project_root or Path.cwd()).resolve()
    register_workspace(resolved_root, global_dir)

    if port <= 0:
        port = DEFAULT_PORT if not _port_open(DEFAULT_PORT) else _find_open_port(DEFAULT_PORT)

    if getattr(sys, "frozen", False):
        cmd = [
            sys.executable,
            "mcp",
            str(resolved_root),
            "--port",
            str(port),
            "--foreground",
        ]
    else:
        main_script = Path(__file__).resolve().parent.parent / "main.py"
        cmd = [
            sys.executable,
            str(main_script),
            "mcp",
            str(resolved_root),
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
        status = get_server_status(global_dir)
        if status and status.get("healthy"):
            return status

    # Check if process crashed immediately
    if proc.poll() is not None:
        return None

    return get_server_status(global_dir)
