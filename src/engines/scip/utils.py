import sys
import subprocess
from collections import deque


def print_progress(current: int, total: int, prefix: str = "", width: int = 30):
    """Print a progress bar that updates in-place."""
    if total == 0:
        return
    pct = current / total
    filled = int(width * pct)
    bar = "=" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r{prefix} [{bar}] {current}/{total} ({pct*100:.0f}%)")
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def run_with_scroll(cmd: list, cwd: str, max_lines: int = 10, shell: bool = False) -> int:
    """
    Runs a subprocess and displays only the last `max_lines` of output.
    Handles both \\n and \\r line endings (for tools like rust-analyzer that use \\r for progress).
    Older lines are removed from the top as new ones appear.
    Returns the process return code.
    """
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        shell=shell,
        bufsize=1
    )

    buffer = deque(maxlen=max_lines)
    lines_printed = 0
    partial_line = ""

    def _redraw():
        nonlocal lines_printed
        if lines_printed > 0:
            sys.stdout.write(f'\033[{lines_printed}A')
        for bline in buffer:
            sys.stdout.write(f'\033[2K{bline}\n')
        leftover = lines_printed - len(buffer)
        for _ in range(leftover):
            sys.stdout.write('\033[2K\n')
        if leftover > 0:
            sys.stdout.write(f'\033[{leftover}A')
        lines_printed = len(buffer)
        sys.stdout.flush()

    try:
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                break
            for char in chunk:
                if char in ('\r', '\n'):
                    if partial_line.strip():
                        buffer.append(partial_line.strip())
                        _redraw()
                    partial_line = ""
                else:
                    partial_line += char
    except (KeyboardInterrupt, SystemExit):
        process.kill()
        raise
    finally:
        if partial_line.strip():
            buffer.append(partial_line.strip())
            _redraw()
        process.stdout.close()

    return process.wait()
