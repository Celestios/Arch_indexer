"""Unified synchronization pipeline across Tree-sitter AST, SCIP semantic indexing, and FFI bridging."""
from contextlib import nullcontext
import logging
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, List, Optional, Set, Tuple

from change_tracker.invalidation import expand_changed_files
from engines.ffi_linker import link_ffi_bridges
from engines.scip.wrapper import detect_languages, ingest_index, parse_index, run_indexer
from engines.treesitter import sync_project_to_db
from utils.helpers import load_config

logger = logging.getLogger(__name__)


def checkpoint_db(repository) -> None:
    """Flushes DuckDB WAL frames into the main .arch/arch.db file."""
    try:
        with repository._db_conn.session() as conn:
            conn.execute("CHECKPOINT")
    except Exception:
        logger.debug("DuckDB CHECKPOINT failed", exc_info=True)


def _session(session_factory: Optional[Callable[[], ContextManager[Any]]]):
    return session_factory() if session_factory is not None else nullcontext()


def sync_workspace(
    repository,
    project_root: Path,
    languages: Optional[List[str]] = None,
    dirty_files: Optional[Set[str]] = None,
    force: bool = False,
    run_ffi: bool = True,
    package_targets: Optional[Set[Tuple[str, Path]]] = None,
    session_factory: Optional[Callable[[], ContextManager[Any]]] = None,
) -> Dict[str, Any]:
    """
    Performs two-tiered synchronization: Tier-1 Tree-sitter AST, Tier-2 SCIP graph, FFI linking, and WAL checkpoint.
    When session_factory is supplied, acquires and releases DuckDB around DB phases only—leaving .arch/arch.db
    completely unlocked while external SCIP indexers (scip_dart, rust-analyzer, scip-python) execute.
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

    scip_changed_files: Optional[Set[str]] = None
    ast_count = 0
    existing_scip_map: Optional[Dict[str, str]] = None

    # Phase 1 (brief DB lock): expand dependents, Tier-1 AST sync, read existing scip_id map
    with _session(session_factory):
        if dirty_files is not None and not force:
            try:
                scip_changed_files = expand_changed_files(repository, list(dirty_files), max_depth=1)
            except Exception:
                logger.exception("Failed to expand dependent files for incremental sync")
                scip_changed_files = set(dirty_files)

        try:
            ast_count = sync_project_to_db(repository, project_root, filepaths=dirty_files, languages=target_langs)
        except Exception:
            logger.exception("Tier-1 Tree-sitter AST sync failed for %s", project_root)

        try:
            existing_scip_map = repository.graph.get_scip_id_map()
        except Exception:
            logger.exception("Failed to load existing scip_id map from DuckDB")

    # Phase 2 (NO DB lock held): run external SCIP indexers and parse binary index in memory
    indexed: List[str] = []
    failed: List[str] = []
    targets = package_targets or {(lang, project_root) for lang in target_langs}
    parsed_batches: List[Tuple[str, Dict[str, Any]]] = []

    for lang, pkg_root in targets:
        index_path = run_indexer(pkg_root, lang)
        if index_path:
            parsed = parse_index(
                index_path,
                project_root,
                changed_files=scip_changed_files,
                existing_scip_map=existing_scip_map,
            )
            parsed_batches.append((lang, parsed))
        elif lang not in failed:
            failed.append(lang)

    # Phase 3 (brief DB lock): ingest parsed SCIP data, link FFI bridges, and checkpoint WAL
    ffi_edges = 0
    if parsed_batches or (run_ffi and len(target_langs) > 1):
        with _session(session_factory):
            for lang, parsed in parsed_batches:
                ingest_index(repository, parsed, project_root=project_root, force=force)
                if lang not in indexed:
                    indexed.append(lang)

            if run_ffi and len(target_langs) > 1:
                try:
                    ffi_edges = link_ffi_bridges(repository, config=load_config(project_root))
                except Exception:
                    logger.exception("FFI bridge linking failed for %s", project_root)

            checkpoint_db(repository)

    return {
        "languages": target_langs,
        "indexed_languages": indexed,
        "failed_languages": failed,
        "ast_symbol_count": ast_count,
        "ffi_edges_created": ffi_edges,
    }
