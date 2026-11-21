"""Tree-sitter AST intelligence engine functions for Arch-mcp."""
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set

from engines.registry import LanguageRegistry
from engines.reconciler import reconcile_symbol_id
from engines.treesitter.loader import detect_language, get_parser, get_language, is_available
from engines.treesitter.extractor import extract_symbols_from_file, SymbolDeclaration
from engines.treesitter.folding import fold_code
from engines.treesitter.rules import check_file
from engines.treesitter.metrics import calculate_metrics
from engines.treesitter.control_flow import get_context_tags, format_context
from engines.treesitter.types_extractor import extract_types
from engines.treesitter.annotations import extract_annotations
from utils.exclusions import load_include_dirs, load_exclude_patterns, is_included, is_excluded


def extract_symbols(
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
    project_root: Optional[Path] = None,
) -> List[SymbolDeclaration]:
    """Extract all symbol declarations from a file."""
    return extract_symbols_from_file(filepath, source, project_root)


def check_rules(
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
) -> List[Dict[str, Any]]:
    """Check for structural anti-patterns (bare excepts, .unwrap(), etc.)."""
    fp = Path(filepath)
    lang = detect_language(fp)
    if not lang:
        return []
    if source is None:
        if not fp.exists():
            return []
        source = fp.read_bytes()
    return check_file(fp, source, lang)


def sync_file_to_db(
    repository,
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
    project_root: Optional[Path] = None,
) -> List[SymbolDeclaration]:
    """Fast Tier-1 synchronization (< 2ms): updates DuckDB files and syntactic symbol columns."""
    fp = Path(filepath)
    if project_root:
        try:
            norm_fp = str(fp.resolve().relative_to(Path(project_root).resolve())).replace("\\", "/")
        except Exception:
            norm_fp = str(filepath).replace("\\", "/")
    else:
        norm_fp = str(filepath).replace("\\", "/")
    if norm_fp.startswith("./"):
        norm_fp = norm_fp[2:]

    if source is None:
        if not fp.exists():
            return []
        code_bytes = fp.read_bytes()
    elif isinstance(source, str):
        code_bytes = source.encode("utf-8")
    else:
        code_bytes = source

    declarations = extract_symbols(fp, code_bytes, project_root=project_root)
    if not declarations:
        return []

    sha256_hash = hashlib.sha256(code_bytes).hexdigest()
    lang = detect_language(fp) or "unknown"

    query_paths = [norm_fp]
    try:
        abs_fp = str(fp.resolve()).replace("\\", "/")
        if abs_fp != norm_fp:
            query_paths.append(abs_fp)
    except Exception:
        pass

    clean_to_existing: Dict[str, str] = {}
    line_to_existing: Dict[int, str] = {}
    coord_list: List[tuple] = []
    for data in repository.graph.get_symbols_for_files(query_paths):
        sym_id = data["symbol"]
        clean_to_existing[data.get("clean_symbol") or sym_id] = sym_id
        s_line = data.get("start_line")
        if s_line is not None:
            line_to_existing[s_line] = sym_id
            coord_list.append((sym_id, s_line))

    symbols_to_upsert = []
    for decl in declarations:
        target_symbol_id = reconcile_symbol_id(
            clean_symbol=decl.clean_symbol,
            start_line=decl.start_line,
            clean_to_existing=clean_to_existing,
            line_to_existing=line_to_existing,
            occ_list=coord_list,
            decl_name=decl.name,
        ) or decl.clean_symbol

        decl.symbol = target_symbol_id
        symbols_to_upsert.append({
            "symbol": target_symbol_id,
            "clean_symbol": decl.clean_symbol,
            "filepath": norm_fp,
            "kind": decl.kind,
            "signature": decl.signature,
            "docstring": decl.docstring,
            "body_hash": decl.body_hash,
            "parent_symbol": decl.parent_symbol,
            "start_line": decl.start_line,
            "start_col": decl.start_col,
            "end_line": decl.end_line,
            "end_col": decl.end_col,
        })

    with repository.transaction():
        repository.workspace.upsert_file(norm_fp, sha256_hash, lang)
        repository.graph.upsert_syntactic_symbols(symbols_to_upsert)

    return declarations


def sync_project_to_db(
    repository,
    project_root: Path,
    filepaths: Optional[Union[Set[str], List[str]]] = None,
    languages: Optional[List[str]] = None,
) -> int:
    """Scans workspace files and synchronizes Tier-1 AST declarations into DuckDB."""
    project_root = Path(project_root)
    include_dirs = load_include_dirs(project_root)
    exclude_patterns = load_exclude_patterns(project_root)
    total_symbols = 0

    target_files = []
    if filepaths:
        for fp in filepaths:
            p = (project_root / fp) if not Path(fp).is_absolute() else Path(fp)
            if p.exists() and p.is_file():
                target_files.append(p)
    else:
        ignore_dirs = {".git", "target", "build", ".dart_tool", "node_modules", ".venv", "__pycache__", ".arch", "dist", "bin"}
        target_roots = [project_root / d for d in include_dirs] if include_dirs else [project_root]
        valid_exts = LanguageRegistry.list_extensions()

        for root_path in target_roots:
            if not root_path.exists():
                continue
            if root_path.is_file():
                target_files.append(root_path)
                continue
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for f in files:
                    if os.path.splitext(f)[1].lower() in valid_exts:
                        p = Path(root) / f
                        try:
                            rel_str = str(p.relative_to(project_root)).replace("\\", "/")
                            if is_excluded(rel_str, exclude_patterns):
                                continue
                            if include_dirs and not is_included(rel_str, include_dirs, exclude_patterns):
                                continue
                            if languages and detect_language(p) not in languages:
                                continue
                            target_files.append(p)
                        except ValueError:
                            continue

    for p in target_files:
        try:
            total_symbols += len(sync_file_to_db(repository, p, project_root=project_root))
        except Exception:
            pass

    return total_symbols


__all__ = [
    "SymbolDeclaration",
    "detect_language",
    "get_parser",
    "get_language",
    "is_available",
    "extract_symbols",
    "extract_symbols_from_file",
    "fold_code",
    "check_rules",
    "check_file",
    "calculate_metrics",
    "get_context_tags",
    "format_context",
    "extract_types",
    "extract_annotations",
    "sync_file_to_db",
    "sync_project_to_db",
]
