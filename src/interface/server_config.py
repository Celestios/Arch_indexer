"""Lazy configuration for the MCP server. Values computed on first access."""
import os
import sys
from pathlib import Path
from typing import Optional

_resolved = {}


def get_project_root() -> Path:
    """Resolve project root from env var or sys.argv."""
    if "project_root" not in _resolved:
        if os.environ.get("ARCH_PROJECT_ROOT"):
            _resolved["project_root"] = Path(os.environ["ARCH_PROJECT_ROOT"]).resolve()
        elif len(sys.argv) > 2 and not sys.argv[2].startswith("-"):
            _resolved["project_root"] = Path(sys.argv[2]).resolve()
        elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
            _resolved["project_root"] = Path(sys.argv[1]).resolve()
        else:
            _resolved["project_root"] = Path.cwd().resolve()
    return _resolved["project_root"]


def get_arch_dir() -> Path:
    return get_project_root() / ".arch"


def get_db_path() -> Path:
    return get_arch_dir() / "arch.db"


def get_bin_dir() -> Path:
    from utils.progress import resolve_bin_dir
    return resolve_bin_dir()
