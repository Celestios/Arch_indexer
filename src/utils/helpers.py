"""Shared DRY utilities for arch-mcp."""
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

IS_WINDOWS = sys.platform == "win32"

CONFIG_DIR_NAME = ".arch"
CONFIG_FILE_NAME = "config.json"

CODEQL_LANG_MAP = {
    "rust": "rust", "go": "go", "java": "java", "python": "python",
    "typescript": "javascript",
}


def config_path_for(project_root: Path) -> Path:
    """Return the canonical path to .arch/config.json."""
    return project_root / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def ext_to_lang(ext: str) -> str:
    """Map file extension to language name."""
    mapping = {
        ".rs": "rust",
        ".dart": "dart",
        ".py": "python",
        ".go": "go",
        ".js": "javascript",
        ".ts": "typescript",
        ".java": "java",
    }
    return mapping.get(ext.lower(), "unknown")


class ViolationId:
    """Generates deterministic violation IDs from component strings."""

    @staticmethod
    def generate(*components: str) -> str:
        text = "_".join(components)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def resolve_filepath(repository, raw_path: str) -> Optional[str]:
    """Resolve a filepath against the database, trying exact match then suffix fallback."""
    file_info = repository.files.get_file(raw_path)
    if file_info:
        return raw_path
    all_files = repository.files.get_all_files_metadata()
    for fp in all_files.keys():
        if fp.replace("\\", "/").endswith(raw_path.replace("\\", "/")):
            return fp
    return None


def matches_filter(filepath: str, filepath_filter: Optional[str]) -> bool:
    """Check if filepath matches the filter prefix. Returns True if no filter."""
    if not filepath_filter:
        return True
    normalized = filepath.replace("\\", "/")
    return normalized.startswith(filepath_filter.replace("\\", "/"))


def find_definition_line(repository, symbol: str, filepath: str) -> int:
    """Find the definition line number for a symbol in a given file. Returns 1 as fallback."""
    occs = repository.symbols.get_occurrences_for_symbol(symbol)
    for occ in occs:
        if occ["filepath"] == filepath and occ["role"] == 1:
            return occ["start_line"]
    if occs:
        return occs[0]["start_line"]
    return 1


def load_config(project_root: Path) -> Dict[str, Any]:
    """Load and parse .arch/config.json."""
    config_path = config_path_for(project_root)
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
