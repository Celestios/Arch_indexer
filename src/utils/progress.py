import sys
from pathlib import Path


def resolve_bin_dir() -> Path:
    """Resolve the bin directory for the project (models, codeql, etc.)."""
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "bin").exists():
            return exe_dir / "bin"
        return exe_dir.parent / "bin"
    return Path(__file__).resolve().parent.parent.parent / "bin"


def make_progress_callback(filename: str):
    """Create a progress callback for download operations."""
    def callback(downloaded: int, total_size: int):
        percent = (downloaded / total_size) * 100 if total_size else 0
        bar_len = 30
        filled_len = int(round(bar_len * downloaded / float(total_size))) if total_size else 0
        bar = '=' * filled_len + '-' * (bar_len - filled_len)
        sys.stdout.write(f"\r[{filename}] [{bar}] {downloaded / (1024*1024):.1f}/{total_size / (1024*1024):.1f} MB ({percent:.1f}%)")
        sys.stdout.flush()
        if downloaded == total_size:
            sys.stdout.write("\n")
    return callback
