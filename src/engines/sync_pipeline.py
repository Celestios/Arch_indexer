"""Unified synchronization pipeline across Tree-sitter AST, SCIP semantic indexing, and FFI bridging."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from engines.ffi_linker import link_ffi_bridges
from engines.scip.wrapper import detect_languages, ingest_index, parse_index, run_indexer
from engines.treesitter import sync_project_to_db
from utils.helpers import load_config

logger = logging.getLogger(__name__)


def sync_workspace(
    repository,
    project_root: Path,
    languages: Optional[List[str]] = None,
    dirty_files: Optional[Set[str]] = None,
    force: bool = False,
    run_ffi: bool = True,
    package_targets: Optional[Set[Tuple[str, Path]]] = None,
) -> Dict[str, Any]:
    """Performs two-tiered synchronization: Tier-1 Tree-sitter AST, Tier-2 SCIP graph, and FFI linking."""
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

    ast_count = 0
    try:
        ast_count = sync_project_to_db(repository, project_root, filepaths=dirty_files, languages=target_langs)
    except Exception:
        logger.exception("Tier-1 Tree-sitter AST sync failed for %s", project_root)

    indexed: List[str] = []
    failed: List[str] = []
    targets = package_targets or {(lang, project_root) for lang in target_langs}
    existing_scip_map: Optional[Dict[str, str]] = None
    try:
        existing_scip_map = repository.graph.get_scip_id_map()
    except Exception:
        logger.exception("Failed to load existing scip_id map from DuckDB")

    for lang, pkg_root in targets:
        index_path = run_indexer(pkg_root, lang)
        if index_path:
            parsed = parse_index(
                index_path,
                project_root,
                changed_files=dirty_files,
                existing_scip_map=existing_scip_map,
            )
            ingest_index(repository, parsed, project_root=project_root, force=force)
            if lang not in indexed:
                indexed.append(lang)
        elif lang not in failed:
            failed.append(lang)

    ffi_edges = 0
    if run_ffi and len(target_langs) > 1:
        try:
            ffi_edges = link_ffi_bridges(repository, config=load_config(project_root))
        except Exception:
            logger.exception("FFI bridge linking failed for %s", project_root)

    return {
        "languages": target_langs,
        "indexed_languages": indexed,
        "failed_languages": failed,
        "ast_symbol_count": ast_count,
        "ffi_edges_created": ffi_edges,
    }
