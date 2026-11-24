"""Shared pure utilities for arch-mcp (strictly layer-local: no DB or engine imports)."""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from utils.arch_config import ArchConfig
from utils.symbol_id import canonical_display_name

IS_WINDOWS = sys.platform == "win32"

CONFIG_DIR_NAME = ".arch"
CONFIG_FILE_NAME = "config.json"


def config_path_for(project_root: Path) -> Path:
    """Return the canonical path to .arch/config.json."""
    return project_root / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def normalize_scopes(scope: Optional[Union[str, List[str]]]) -> Optional[List[str]]:
    """Normalizes comma-separated, JSON array, or list scopes to clean POSIX path prefixes."""
    if scope is None:
        return None
    if isinstance(scope, str):
        stripped = scope.strip()
        if stripped.startswith("["):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, list):
                    raw_items = [str(s).strip() for s in loaded if str(s).strip()]
                else:
                    raw_items = [stripped]
            except Exception:
                raw_items = [s.strip() for s in stripped.split(",") if s.strip()]
        else:
            raw_items = [s.strip() for s in stripped.split(",") if s.strip()]
    else:
        raw_items = [str(s).strip() for s in scope if str(s).strip()]

    cleaned = [
        p.replace("\\", "/").rstrip("/")
        for p in raw_items
        if p and p.replace("\\", "/").rstrip("/") not in (".", "./", "*", "all", "")
    ]
    return cleaned or None


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
    except OSError:
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
    """Load, validate, and normalize .arch/config.json into an ArchConfig."""
    config_path = config_path_for(project_root)
    if not config_path.exists():
        return ArchConfig()
    config, _ = ArchConfig.parse_and_validate(config_path)
    return config if config is not None else ArchConfig()


AUXILIARY_PATH_PARTS = {
    "test", "tests", "testing", "example", "examples",
    "sample", "samples", "bench", "benches", "benchmark",
    "benchmarks", "fixture", "fixtures", "mock", "mocks", "stub", "stubs",
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


def infer_scip_kind(raw_scip: Optional[str]) -> str:
    """Infer symbol kind strictly from raw SCIP descriptor suffixes."""
    if not raw_scip:
        return "Symbol"
    if raw_scip.endswith(")") and not raw_scip.endswith("()"):
        return "Parameter"
    if raw_scip.endswith("$"):
        return "Macro"
    if raw_scip.endswith(":"):
        return "TypeParameter"
    if raw_scip.endswith("/__init__:") or raw_scip.endswith("/"):
        return "Module"
    if raw_scip.endswith("#") or raw_scip.endswith("#."):
        return "Class"
    if raw_scip.endswith("().") or raw_scip.endswith("()"):
        if "#" in raw_scip:
            if "__init__" in raw_scip or "constructor" in raw_scip or "#new()" in raw_scip:
                return "Constructor"
            return "Method"
        return "Function"
    if raw_scip.endswith("."):
        return "Field"
    return "Symbol"


def sanitize_docstring(doc: Optional[str]) -> str:
    """Sanitize docstrings so they do not break Markdown rendering."""
    if not doc:
        return ""
    return doc.replace("```", "'''")


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
    if filepath and is_auxiliary_path(filepath):
        return True
    if not sym:
        return False
    disp = canonical_display_name(sym).lower()
    return (
        disp.startswith("test_")
        or disp.endswith("_test")
        or "::test_" in disp
    )


def detect_entry_point(sym: str, filepath: Optional[str] = None, incoming_count: int = 0) -> Optional[str]:
    """Detects if a symbol is a system entry point (main, MCP endpoint, FFI bridge, or root caller)."""
    disp = canonical_display_name(sym)
    fp = (filepath or "").replace("\\", "/").lower()

    if disp == "main" or disp.endswith("::main"):
        return "System Entry: `main()`"
    if "interface/tools" in fp or "interface/server" in fp:
        return "MCP Tool Endpoint"
    if "bridge" in fp or "ffi" in fp:
        return "FFI Export / Bridge"
    if incoming_count == 0 and not is_test_caller(sym, filepath):
        return "Root Caller (No Upstream)"
    return None
