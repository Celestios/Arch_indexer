"""Shared DRY utilities for arch-mcp."""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.violation_id import ViolationId
from engines.registry import LanguageRegistry

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
    if not ext.startswith("."):
        ext = "." + ext
    lang = LanguageRegistry.detect_language(ext)
    if lang:
        return lang
    mapping = {
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "cpp",
        ".cs": "csharp",
        ".rb": "ruby",
        ".php": "php",
        ".html": "html",
        ".css": "css",
        ".sh": "bash",
        ".ps1": "powershell",
    }
    return mapping.get(ext.lower(), "unknown")


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
