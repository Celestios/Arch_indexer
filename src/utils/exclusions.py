import json
from pathlib import Path
from typing import Set, Optional


def load_include_dirs(project_root: Path) -> Optional[Set[str]]:
    """Load included directories from .arch/config.json keys.
    Each top-level key represents a directory to index.
    Returns None if config is empty or missing.
    """
    config_path = project_root / ".arch" / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        dirs = [k for k, v in config.items() if isinstance(v, dict)]
        if dirs:
            return set(dirs)
    except Exception:
        pass
    return None


def is_included(rel_path: str, include_dirs: Set[str]) -> bool:
    """Check if a relative path is within one of the included directories."""
    parts = Path(rel_path).parts
    # For each include_dir (e.g. "src"), check if it appears at the correct depth.
    # A dir like "src" must be at index 0 (top-level). A dir like "src/engines"
    # must match parts[0:2], etc.
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
