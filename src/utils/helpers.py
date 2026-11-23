"""Shared DRY utilities for arch-mcp."""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.arch_config import ArchConfig
from engines.registry import LanguageRegistry

IS_WINDOWS = sys.platform == "win32"

CONFIG_DIR_NAME = ".arch"
CONFIG_FILE_NAME = "config.json"


def config_path_for(project_root: Path) -> Path:
    """Return the canonical path to .arch/config.json."""
    return project_root / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def ext_to_lang(ext: str) -> str:
    """Map file extension to language name via LanguageRegistry."""
    if not ext.startswith("."):
        ext = "." + ext
    return LanguageRegistry.detect_language(ext) or "unknown"


def resolve_filepath(repository, raw_path: str) -> Optional[str]:
    """Resolve a filepath against the database, trying exact match then suffix fallback."""
    file_info = repository.workspace.get_file(raw_path)
    if file_info:
        return raw_path
    all_files = repository.workspace.get_all_files_metadata()
    norm_raw = raw_path.replace("\\", "/")
    for fp in all_files.keys():
        if fp.replace("\\", "/").endswith(norm_raw):
            return fp
    return None


def matches_filter(filepath: str, filepath_filter: Optional[str]) -> bool:
    """Check if filepath matches the filter prefix. Returns True if no filter."""
    if not filepath_filter:
        return True
    return filepath.replace("\\", "/").startswith(filepath_filter.replace("\\", "/"))


def extract_code_slice(
    filepath: str,
    start_line: Optional[int],
    end_line: Optional[int],
    project_root: Optional[Path] = None,
) -> Optional[str]:
    """Reads source lines from disk using 1-based start_line and end_line coordinates."""
    if not start_line or not end_line or start_line <= 0:
        return None
    p = Path(filepath)
    if not p.is_absolute() and project_root:
        p = project_root / p
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        s_idx = max(0, start_line - 1)
        e_idx = min(len(lines), end_line)
        return "".join(lines[s_idx:e_idx]).rstrip()
    except Exception:
        return None


def find_call_site_or_definition_line(
    source_sym: str,
    target_sym: str,
    edge: Optional[Dict[str, Any]] = None,
    snapshot: Optional[Any] = None,
) -> int:
    """Resolve call site line from edge or snapshot, falling back to source definition line."""
    if edge and edge.get("call_line"):
        return edge["call_line"]

    if snapshot is not None:
        for incoming_edge in snapshot.get_incoming(target_sym):
            if incoming_edge.get("source") == source_sym and incoming_edge.get("call_line"):
                return incoming_edge["call_line"]
        def_info = snapshot.get_definition(source_sym)
        if def_info and def_info.get("start_line"):
            return def_info["start_line"]
        sym_info = snapshot.get_symbol(source_sym)
        if sym_info and sym_info.get("start_line"):
            return sym_info["start_line"]

    return 1


def load_config(project_root: Path) -> ArchConfig:
    """Load, validate, and normalize .arch/config.json into an ArchConfig.

    Returns an empty ArchConfig when the file is missing or fails validation.
    """
    config_path = config_path_for(project_root)
    if not config_path.exists():
        return ArchConfig()
    config, _ = ArchConfig.parse_and_validate(config_path)
    return config if config is not None else ArchConfig()


def demangle_scip_symbol(sym: Optional[str]) -> str:
    """Demangle a SCIP symbol into a clean, human-readable identifier."""
    if not sym:
        return ""
    if sym.startswith("local "):
        return sym

    parts = sym.split(" ", 4)
    if len(parts) == 5 and (parts[0].startswith("scip-") or "/" in parts[4] or "#" in parts[4] or "`" in parts[4]):
        descriptor = parts[4]
    else:
        descriptor = sym

    s = descriptor.replace("`", "").replace("/", ".").replace("#", ".")
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
    for p in parts[:-1]:
        if p in AUXILIARY_PATH_PARTS:
            return True

    filename = parts[-1]
    name_no_ext = filename.rsplit(".", 1)[0] if "." in filename else filename
    return (
        name_no_ext.startswith("test_")
        or name_no_ext.endswith("_test")
        or name_no_ext.endswith(".test")
        or name_no_ext.endswith("_spec")
        or name_no_ext.endswith(".spec")
        or name_no_ext.endswith("_bench")
        or name_no_ext.endswith(".bench")
    )


def score_definition_candidate(
    defn: Dict[str, Any],
    filepath: Optional[str] = None,
    start_line: int = 1,
    end_line: int = 1,
) -> int:
    """Compute a deterministic score for canonical symbol disambiguation."""
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


def resolve_symbol_in_repo(repository, target: str) -> Optional[Dict[str, Any]]:
    """Resolve a target string to an exact symbol dict from the database."""
    target_clean = target.strip()
    if not target_clean:
        return None

    exact = repository.graph.get_symbol(target_clean)
    if exact:
        return exact

    t = target_clean[:-2] if target_clean.endswith("()") else target_clean
    patterns = [t]
    if "." in t:
        parts = [p for p in t.split(".") if p]
        patterns.append(parts[-1])

    for p in patterns:
        raw_cands = repository.graph.search_symbols(p, limit=50)
        candidates = [
            s for s in raw_cands
            if not s["symbol"].startswith("local ")
            and not (s["symbol"].endswith(")") and not s["symbol"].endswith("()"))
        ]
        if candidates:
            def score(s):
                dem = s.get("clean_symbol") or demangle_scip_symbol(s["symbol"])
                dem_no_parens = dem[:-2] if dem.endswith("()") else dem
                is_test = is_auxiliary_path(s.get("filepath"))
                is_exact = (dem == t or dem_no_parens == t or dem.endswith("." + t) or dem_no_parens.endswith("." + t))
                return (0 if is_exact else 1, 1 if is_test else 0, len(s["symbol"]))

            candidates.sort(key=score)
            return candidates[0]

    return None


def format_classification_badge(raw: Any) -> str:
    """Formats symbol classification dictionary or JSON string into a compact badge."""
    if not raw:
        return ""
    fields = raw
    if isinstance(raw, str):
        try:
            fields = json.loads(raw)
        except Exception:
            return ""
    if not isinstance(fields, dict) or not fields:
        return ""
    parts = []
    order = ["layer", "tier", "stability"]
    for k in order:
        if k in fields and fields[k]:
            parts.append(f"{k}: {fields[k]}")
    for k, v in sorted(fields.items()):
        if k not in order and v:
            parts.append(f"{k}: {v}")
    if not parts:
        return ""
    return f"[{', '.join(parts)}]"


def is_test_caller(sym: str, filepath: Optional[str] = None, role: int = 0) -> bool:
    """Checks if a symbol corresponds to a test definition or occurrence."""
    if role & 0x20:
        return True
    if filepath:
        fp_norm = filepath.replace("\\", "/").lower()
        if (
            fp_norm.startswith(("test/", "tests/"))
            or "/test/" in fp_norm
            or "/tests/" in fp_norm
            or fp_norm.endswith(("_test.dart", "_test.py", "_test.rs", "_test.go", ".test.ts", ".test.js"))
            or "test_" in fp_norm
        ):
            return True
    s_clean = demangle_scip_symbol(sym).lower()
    return (
        s_clean.startswith("test_")
        or s_clean.endswith("_test")
        or ".test_" in s_clean
        or "::test_" in s_clean
    )


def detect_entry_point(sym: str, filepath: Optional[str] = None, incoming_count: int = 0) -> Optional[str]:
    """Detects if a symbol is a system entry point (main, MCP endpoint, FFI bridge, or root caller)."""
    clean = demangle_scip_symbol(sym)
    fp = (filepath or "").replace("\\", "/").lower()

    if clean in ("main", "main()") or clean.endswith(".main") or clean.endswith(".main()"):
        return "System Entry: `main()`"
    if "interface/tools" in fp or "interface.tools" in clean or "interface/server" in fp:
        return "MCP Tool Endpoint"
    if "bridge" in fp or "ffi" in fp:
        return "FFI Export / Bridge"
    if incoming_count == 0 and not is_test_caller(sym, filepath):
        return "Root Caller (No Upstream)"
    return None

