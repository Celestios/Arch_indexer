import logging
import subprocess
import sys
from collections import deque

logger = logging.getLogger(__name__)


def print_progress(current: int, total: int, prefix: str = "", width: int = 30):
    """Print a progress bar to stderr (never stdout, preserving MCP stdio JSON-RPC framing)."""
    if total == 0:
        return
    if not sys.stderr.isatty():
        if current >= total:
            logger.debug("%s %d/%d (100%%)", prefix, current, total)
        return
    pct = current / total
    filled = int(width * pct)
    bar = "=" * filled + "-" * (width - filled)
    sys.stderr.write(f"\r{prefix} [{bar}] {current}/{total} ({pct * 100:.0f}%)")
    sys.stderr.flush()
    if current >= total:
        sys.stderr.write("\n")


def run_with_scroll(cmd: list, cwd: str, max_lines: int = 10, shell: bool = False) -> int:
    """
    Runs a subprocess safely with stdin detached (DEVNULL) and never writes to sys.stdout.
    Renders a scrolling ANSI viewport to sys.stderr when attached to a TTY, or logs output otherwise.
    Returns the process return code.
    """
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=shell,
        bufsize=1,
        creationflags=creationflags,
    )

    use_tty = sys.stderr.isatty()
    buffer = deque(maxlen=max_lines)
    lines_printed = 0
    partial_line = ""

    def _redraw():
        nonlocal lines_printed
        if not use_tty:
            return
        if lines_printed > 0:
            sys.stderr.write(f"\033[{lines_printed}A")
        for bline in buffer:
            sys.stderr.write(f"\033[2K{bline}\n")
        leftover = lines_printed - len(buffer)
        for _ in range(leftover):
            sys.stderr.write("\033[2K\n")
        if leftover > 0:
            sys.stderr.write(f"\033[{leftover}A")
        lines_printed = len(buffer)
        sys.stderr.flush()

    try:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                break
            for char in chunk:
                if char in ("\r", "\n"):
                    stripped = partial_line.strip()
                    if stripped:
                        buffer.append(stripped)
                        if use_tty:
                            _redraw()
                        else:
                            logger.debug("[SCIP] %s", stripped)
                    partial_line = ""
                else:
                    partial_line += char
    except (KeyboardInterrupt, SystemExit):
        process.kill()
        raise
    finally:
        stripped = partial_line.strip()
        if stripped:
            buffer.append(stripped)
            if use_tty:
                _redraw()
            else:
                logger.debug("[SCIP] %s", stripped)
        if process.stdout is not None:
            process.stdout.close()

    rc = process.wait()
    if rc != 0 and buffer and not use_tty:
        logger.warning("[SCIP] Command %s exited with %d; last output:\n%s", cmd[0], rc, "\n".join(buffer))
    return rc
