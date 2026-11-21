from pathlib import Path
from typing import Set, Optional, List

from utils.helpers import load_config


def load_include_dirs(project_root: Path) -> Optional[Set[str]]:
    """Load included directories from .arch/config.json keys.
    Each top-level key with a dictionary value represents a directory to index.
    Returns None if config is empty or missing.
    """
    config = load_config(project_root)
    if not config:
        return None
    dirs = [k for k in config.prefixes.keys() if k != "."]
    return set(dirs) if dirs else None


def load_exclude_patterns(project_root: Optional[Path]) -> List[str]:
    """Load top-level exclusion patterns from .arch/config.json 'exclude' key.
    Can be a list of strings (e.g. ['lib/src/**', '**/target/**']).
    """
    if not project_root:
        return []
    config = load_config(project_root)
    return list(config.exclude)


DEFAULT_EXCLUDED_DIRS = {
    ".git", ".arch", ".venv", "venv", "node_modules", "bin", "__pycache__", "dist", "build"
}


def matches_glob(rel_path: str, pattern: str) -> bool:
    """Matches a relative path against a glob pattern in a cross-platform way."""
    from pathlib import PurePosixPath
    norm_path = rel_path.replace("\\", "/").strip("/")
    norm_pat = pattern.replace("\\", "/").strip("/")

    # Handle recursive directory prefix pattern like "lib/src/**"
    if norm_pat.endswith("/**"):
        prefix = norm_pat[:-3]
        if norm_path == prefix or norm_path.startswith(prefix + "/"):
            return True

    # If pattern has no wildcards, treat as exact or directory prefix match
    if not any(c in norm_pat for c in "*?[]"):
        if norm_path == norm_pat or norm_path.startswith(norm_pat + "/"):
            return True

    try:
        if PurePosixPath(norm_path).match(norm_pat):
            return True
    except Exception:
        pass

    return False


def is_excluded(rel_path: str, exclude_patterns: Optional[List[str]] = None) -> bool:
    """Check if a path falls into common ignored directories or matches exclusion patterns."""
    norm_path = rel_path.replace("\\", "/")
    parts = Path(norm_path).parts
    if any(p in DEFAULT_EXCLUDED_DIRS for p in parts):
        return True

    if exclude_patterns:
        for pat in exclude_patterns:
            if matches_glob(norm_path, pat):
                return True

    return False


def is_included(rel_path: str, include_dirs: Set[str], exclude_patterns: Optional[List[str]] = None) -> bool:
    """Check if a relative path is within one of the included directories and not excluded."""
    if is_excluded(rel_path, exclude_patterns):
        return False
    parts = Path(rel_path.replace("\\", "/")).parts
    for inc in include_dirs:
        inc_parts = tuple(Path(inc.replace("\\", "/")).parts)
        depth = len(inc_parts)
        if len(parts) >= depth and parts[:depth] == inc_parts:
            return True
    return False


def filter_paths(paths, project_root: Path, include_dirs: Optional[Set[str]] = None,
                 exclude_patterns: Optional[List[str]] = None):
    """Filter paths, keeping only those within included directories and not excluded."""
    if include_dirs is None:
        include_dirs = load_include_dirs(project_root)
    if exclude_patterns is None:
        exclude_patterns = load_exclude_patterns(project_root)

    for p in paths:
        try:
            rel = p.relative_to(project_root)
        except ValueError:
            if not is_excluded(str(p), exclude_patterns):
                yield p
            continue
        if is_excluded(str(rel), exclude_patterns):
            continue
        if include_dirs is None:
            yield p
            continue
        if is_included(str(rel), include_dirs, exclude_patterns):
            yield p

