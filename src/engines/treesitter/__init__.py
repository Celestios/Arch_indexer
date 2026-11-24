"""Tree-sitter AST intelligence engine functions for Arch-mcp."""
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from engines.registry import LanguageRegistry
from engines.treesitter.annotations import extract_annotations
from engines.treesitter.control_flow import format_context, get_context_tags
from engines.treesitter.extractor import SymbolDeclaration, extract_di_edges, extract_symbols_from_file
from engines.treesitter.folding import fold_code
from engines.treesitter.loader import detect_language, get_language, get_parser, is_available
from engines.treesitter.metrics import calculate_metrics
from engines.treesitter.rules import check_file
from engines.treesitter.types_extractor import extract_types
from utils.exclusions import (
    DEFAULT_EXCLUDED_DIRS,
    is_excluded,
    is_included,
    load_exclude_patterns,
    load_include_dirs,
)

logger = logging.getLogger(__name__)


def extract_symbols(
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
    project_root: Optional[Path] = None,
) -> List[SymbolDeclaration]:
    """Extract all canonical symbol declarations from a file."""
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
    leaf_symbol_map: Optional[Dict[str, str]] = None,
    commit: bool = True,
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

    symbols_to_upsert = [
        {
            "symbol": decl.symbol,
            "name": decl.name,
            "scip_id": None,
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
        }
        for decl in declarations
    ]

    raw_di_edges = extract_di_edges(fp, code_bytes, project_root=project_root, declarations=declarations)
    injects_to_upsert: List[Dict[str, Any]] = []
    if raw_di_edges:
        seen_injects = set()
        for item in raw_di_edges:
            t_name = item["target_name"]
            resolved_target = leaf_symbol_map.get(t_name) if leaf_symbol_map is not None else None
            if not resolved_target and leaf_symbol_map is None:
                for m in repository.graph.search_symbols(t_name, limit=10):
                    if m.get("name") == t_name:
                        resolved_target = m["symbol"]
                        break
            if resolved_target and resolved_target != item["source"]:
                edge_key = (item["source"], resolved_target)
                if edge_key not in seen_injects:
                    seen_injects.add(edge_key)
                    injects_to_upsert.append({
                        "source": item["source"],
                        "target": resolved_target,
                        "relation": "Injects",
                        "weight": 0.9,
                        "call_line": item["call_line"],
                    })

    deduped_symbols = list({s["symbol"]: s for s in symbols_to_upsert}.values())

    if commit:
        with repository.transaction():
            repository.workspace.upsert_ast_file(norm_fp, sha256_hash, lang)
            repository.graph.upsert_syntactic_symbols(deduped_symbols)
            if injects_to_upsert:
                repository.graph.upsert_edges(injects_to_upsert)
    else:
        repository.workspace.upsert_ast_file(norm_fp, sha256_hash, lang)
        repository.graph.upsert_syntactic_symbols(deduped_symbols)
        if injects_to_upsert:
            repository.graph.upsert_edges(injects_to_upsert)

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
        target_roots = [project_root / d for d in include_dirs] if include_dirs else [project_root]
        valid_exts = LanguageRegistry.list_extensions()

        for root_path in target_roots:
            if not root_path.exists():
                continue
            if root_path.is_file():
                target_files.append(root_path)
                continue
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDED_DIRS and not d.startswith(".")]
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

    with repository.transaction():
        existing_syms = repository.graph.get_all_symbols()
        leaf_map: Dict[str, str] = {}
        for s in existing_syms:
            leaf = s.get("name")
            if leaf and leaf not in leaf_map:
                leaf_map[leaf] = s["symbol"]

        for p in target_files:
            try:
                decls = sync_file_to_db(
                    repository,
                    p,
                    project_root=project_root,
                    leaf_symbol_map=leaf_map,
                    commit=False,
                )
                for d in decls:
                    if d.name and d.symbol:
                        leaf_map[d.name] = d.symbol
                total_symbols += len(decls)
            except Exception:
                logger.exception("Failed Tree-sitter AST sync for %s", p)

    return total_symbols


__all__ = [
    "SymbolDeclaration",
    "detect_language",
    "get_parser",
    "get_language",
    "is_available",
    "extract_symbols",
    "extract_symbols_from_file",
    "extract_di_edges",
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
