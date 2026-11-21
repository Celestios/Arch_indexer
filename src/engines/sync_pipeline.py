"""
Unified synchronization pipeline across AST extraction, SCIP semantic indexing, and FFI bridging.
Single source of truth used by CLI init, MCP update, and filesystem watcher.
"""
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from engines.scip.wrapper import detect_languages, run_indexer, parse_index, ingest_index
from engines.treesitter import TreesitterEngine
from engines.ffi_linker import FfiLinker


def sync_workspace(
    repository,
    project_root: Path,
    languages: Optional[List[str]] = None,
    dirty_files: Optional[Set[str]] = None,
    force: bool = False,
    run_ffi: bool = True,
    package_targets: Optional[Set[tuple[str, Path]]] = None,
) -> Dict[str, Any]:
    """
    Performs two-tiered synchronization:
    1. Fast Tree-sitter AST extraction (< 2ms per file) for declarations, signatures, docstrings, and metrics.
    2. SCIP semantic indexing for cross-file call graphs, occurrences, and diagnostics.
    3. Cross-language FFI bridge linking when multiple languages are present.
    """
    if package_targets:
        target_langs = list({lang for lang, _ in package_targets})
    else:
        target_langs = languages or detect_languages(project_root)

    if not target_langs:
        return {
            "languages": [],
            "indexed_languages": [],
            "failed_languages": [],
            "ast_symbol_count": 0,
            "ffi_edges_created": 0,
        }

    # Stage 1: Tree-sitter AST Sync
    ast_count = 0
    try:
        ast_count = TreesitterEngine.sync_project_to_db(
            repository, project_root, filepaths=dirty_files, languages=target_langs
        )
    except Exception:
        pass

    # Stage 2: SCIP Semantic Graph Sync
    indexed = []
    failed = []
    targets = package_targets or {(lang, project_root) for lang in target_langs}
    for lang, pkg_root in targets:
        index_path = run_indexer(pkg_root, lang)
        if index_path:
            parsed = parse_index(index_path, project_root, changed_files=dirty_files)
            ingest_index(repository, parsed, project_root=project_root, force=force)
            if lang not in indexed:
                indexed.append(lang)
        else:
            if lang not in failed:
                failed.append(lang)

    # Stage 3: FFI Bridge Linking
    ffi_edges = 0
    if run_ffi and (len(target_langs) > 1 or ("dart" in target_langs and "rust" in target_langs)):
        try:
            linker = FfiLinker(repository)
            ffi_edges = linker.link_scip_bridges()
        except Exception:
            pass

    return {
        "languages": target_langs,
        "indexed_languages": indexed,
        "failed_languages": failed,
        "ast_symbol_count": ast_count,
        "ffi_edges_created": ffi_edges,
    }
