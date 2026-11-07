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


def demangle_scip_symbol(sym: Optional[str]) -> str:
    """Demangle a SCIP symbol into a clean, human-readable identifier.
    Strips package prefixes (e.g. 'scip-python python Arch_indexer 0.1.0 '),
    backticks, and converts SCIP descriptor delimiters to clean dot notation.
    """
    if not sym:
        return ""
    if sym.startswith("local "):
        return sym

    parts = sym.split(" ", 4)
    if len(parts) == 5 and (parts[0].startswith("scip-") or "/" in parts[4] or "#" in parts[4] or "`" in parts[4]):
        descriptor = parts[4]
    else:
        descriptor = sym

    # Strip backticks
    s = descriptor.replace("`", "")

    # Convert SCIP descriptor delimiters:
    # / -> .
    # # -> .
    s = s.replace("/", ".").replace("#", ".")
    while s.endswith(".") or s.endswith(":"):
        s = s[:-1]
    return s


AUXILIARY_PATH_PARTS = {
    "test", "tests", "testing", "example", "examples",
    "sample", "samples", "bench", "benches", "benchmark",
    "benchmarks", "fixture", "fixtures", "mock", "mocks", "stub", "stubs"
}


def is_auxiliary_path(filepath: Optional[str]) -> bool:
    """Language-agnostic check if a filepath belongs to test, benchmark, or auxiliary code."""
    if not filepath:
        return False
    norm = filepath.replace("\\", "/").lower()
    parts = norm.split("/")
    # Check directory components
    for p in parts[:-1]:
        if p in AUXILIARY_PATH_PARTS:
            return True

    # Check filename conventions across languages (*_test.*, *.test.*, test_*.*, *_spec.*, *.spec.*)
    filename = parts[-1]
    name_no_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
    if (
        name_no_ext.startswith("test_")
        or name_no_ext.endswith("_test")
        or name_no_ext.endswith(".test")
        or name_no_ext.endswith("_spec")
        or name_no_ext.endswith(".spec")
        or name_no_ext.endswith("_bench")
        or name_no_ext.endswith(".bench")
    ):
        return True
    return False


def score_definition_candidate(defn: Dict[str, Any], filepath: Optional[str] = None,
                               start_line: int = 1, end_line: int = 1) -> int:
    """Compute a deterministic score for canonical symbol disambiguation.
    Score = (is_primary * 100) + (has_signature * 10) + (has_docstring * 5) + min(span, 50).
    """
    fp = filepath or defn.get("filepath")
    is_primary = 1 if (fp and not is_auxiliary_path(fp)) else 0
    sig = defn.get("signature")
    has_sig = 1 if (sig and str(sig).strip()) else 0
    doc = defn.get("docstring")
    has_doc = 1 if (doc and str(doc).strip()) else 0
    s_line = start_line if start_line is not None else defn.get("start_line", 1)
    e_line = end_line if end_line is not None else defn.get("end_line", s_line)
    span = max(0, (e_line - s_line) if (e_line is not None and s_line is not None) else 0)
    span_score = min(span, 50)
    return (is_primary * 100) + (has_sig * 10) + (has_doc * 5) + span_score


def infer_scip_kind(sym: Optional[str]) -> str:
    """Infer symbol kind from standard SCIP descriptor suffixes across languages."""
    if not sym:
        return "Symbol"
    if sym.endswith(")") and not sym.endswith("()"):
        return "Parameter"
    if sym.endswith("$"):
        return "Macro"
    if sym.endswith(":"):
        return "TypeParameter"
    if sym.endswith("/__init__:") or sym.endswith("/"):
        return "Module"
    if sym.endswith("#") or sym.endswith("#."):
        return "Class"
    if sym.endswith("().") or sym.endswith("()"):
        if "#" in sym:
            if "__init__" in sym or "constructor" in sym or "new" in sym:
                return "Constructor"
            return "Method"
        return "Function"
    if sym.endswith("."):
        return "Field"
    clean = demangle_scip_symbol(sym)
    name = clean.rsplit(".", 1)[-1] if "." in clean else clean
    if name.endswith("()"):
        return "Function"
    if "." in clean:
        return "Method"
    return "Symbol"


def sanitize_docstring(doc: Optional[str]) -> str:
    """Sanitize docstrings so they do not break Markdown rendering."""
    if not doc:
        return ""
    return doc.replace("```", "'''")


def resolve_symbol_in_repo(repository, target: str) -> Optional[tuple]:
    """Resolve a target string to an exact symbol tuple from the database.
    Tries exact match, dot-to-delimiter patterns, and priority-scored candidates
    (preferring production src/ over tests/ and excluding parameter definitions).
    Returns (symbol, filepath, kind, signature, docstring, body_hash) or None.
    """
    target_clean = target.strip()
    if not target_clean:
        return None

    # 1. Exact match
    exact = repository.symbols.get_symbol_exact(target_clean)
    if exact:
        return exact

    # 2. Match by substring/keyword in DuckDB
    t = target_clean[:-2] if target_clean.endswith("()") else target_clean
    patterns = [f"%{t}%"]
    if "." in t:
        parts = [p for p in t.split(".") if p]
        patterns.append("%" + "%".join(parts) + "%")

    with repository.db_conn.session() as conn:
        for p in patterns:
            rows = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash FROM symbols WHERE symbol LIKE ? LIMIT 50",
                (p,)
            ).fetchall()
            if rows:
                candidates = [
                    r for r in rows
                    if not r[0].startswith("local ")
                    and not (r[0].endswith(")") and not r[0].endswith("()"))
                ]
                if candidates:
                    def score(c):
                        dem = demangle_scip_symbol(c[0])
                        dem_no_parens = dem[:-2] if dem.endswith("()") else dem
                        is_test = is_auxiliary_path(c[1])
                        exact = (dem == t or dem_no_parens == t or dem.endswith("." + t) or dem_no_parens.endswith("." + t))
                        # Priority: exact demangled match > production code > shorter symbol name
                        return (0 if exact else 1, 1 if is_test else 0, len(c[0]))

                    candidates.sort(key=score)
                    return candidates[0]

    return None

