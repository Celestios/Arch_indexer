from pathlib import Path
from typing import Set, Optional

from utils.helpers import load_config


def load_include_dirs(project_root: Path) -> Optional[Set[str]]:
    """Load included directories from .arch/config.json keys.
    Each top-level key represents a directory to index.
    Returns None if config is empty or missing.
    """
    config = load_config(project_root)
    if not config:
        return None
    dirs = [k for k, v in config.items() if isinstance(v, dict)]
    return set(dirs) if dirs else None


def is_included(rel_path: str, include_dirs: Set[str]) -> bool:
    """Check if a relative path is within one of the included directories."""
    parts = Path(rel_path).parts
    for inc in include_dirs:
        inc_parts = tuple(Path(inc).parts)
        depth = len(inc_parts)
        if len(parts) >= depth and parts[:depth] == inc_parts:
            return True
    return False


def filter_paths(paths, project_root: Path, include_dirs: Optional[Set[str]] = None):
    """Filter paths, keeping only those within included directories. None = include all."""
    if include_dirs is None:
        include_dirs = load_include_dirs(project_root)
    for p in paths:
        if include_dirs is None:
            yield p
            continue
        try:
            rel = p.relative_to(project_root)
        except ValueError:
            yield p
            continue
        if is_included(str(rel), include_dirs):
            yield p
