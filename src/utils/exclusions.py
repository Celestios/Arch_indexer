import json
import sys
from pathlib import Path, PurePosixPath
from typing import Set, Optional, List

from utils.arch_config import ArchConfig
from utils.helpers import config_path_for, load_config


def _load_scope_config(project_root: Path) -> Optional[ArchConfig]:
    """Loads ArchConfig for directory/exclusion filtering without collapsing on rule-validation errors."""
    config = load_config(project_root)
    if config is not None and (config.prefixes or config.exclude):
        return config

    config_path = config_path_for(project_root)
    if not config_path.exists():
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        fallback = ArchConfig.from_dict(raw)
        if fallback.prefixes or fallback.exclude:
            print(
                f"[Arch] Warning: {config_path} has validation errors; "
                "using its directory prefixes and exclude patterns for indexing scope.",
                file=sys.stderr,
            )
            return fallback
    except Exception:
        pass
    return config


def load_include_dirs(project_root: Path) -> Optional[Set[str]]:
    """Load included directories from .arch/config.json keys.
    Returns None if no directory prefixes are configured.
    """
    config = _load_scope_config(project_root)
    if config is None:
        return None
    dirs = [k for k in config.prefixes.keys() if k != "."]
    return set(dirs) if dirs else None


def load_exclude_patterns(project_root: Optional[Path]) -> List[str]:
    """Load top-level exclusion patterns from .arch/config.json 'exclude' key."""
    if not project_root:
        return []
    config = _load_scope_config(project_root)
    if config is None:
        return []
    return list(config.exclude)


DEFAULT_EXCLUDED_DIRS = {
    ".git", ".arch", ".venv", "venv", "node_modules", "bin", "__pycache__", "dist", "build"
}


def matches_glob(rel_path: str, pattern: str) -> bool:
    """Matches a relative path against a glob pattern in a cross-platform way."""
    norm_path = rel_path.replace("\\", "/").strip("/")
    norm_pat = pattern.replace("\\", "/").strip("/")

    if norm_pat.endswith("/**"):
        prefix = norm_pat[:-3]
        if norm_path == prefix or norm_path.startswith(prefix + "/"):
            return True

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


def filter_paths(
    paths,
    project_root: Path,
    include_dirs: Optional[Set[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
):
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
