"""Incremental SCIP semantic ingestion into DuckDB using canonical symbol identity."""
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from change_tracker.invalidation import expand_changed_files
from change_tracker.tracker import calculate_sha256
from engines.registry import LanguageRegistry
from utils.symbol_id import parse_canonical_id

logger = logging.getLogger(__name__)


def _resolve_changed_and_deleted(
    repository,
    parsed_data: Dict[str, Any],
    project_root: Optional[Path] = None,
    force: bool = False,
) -> Tuple[List[str], List[str], List[str], List[str], bool]:
    """Resolves changed files, deleted files, unchanged files, and full-index shrink-guard checks."""
    is_partial = bool(parsed_data.get("is_partial"))
    files_to_register = set()
    for f in parsed_data.get("files", []):
        if f:
            files_to_register.add(f.replace("\\", "/"))
    for occ in parsed_data.get("occurrences", []):
        if occ.get("filepath"):
            files_to_register.add(occ["filepath"].replace("\\", "/"))
    for sym in parsed_data.get("symbols", {}).values():
        if sym.get("filepath"):
            files_to_register.add(sym["filepath"].replace("\\", "/"))

    file_list = list(files_to_register)
    languages_in_index = {LanguageRegistry.detect_language(fp) or "unknown" for fp in file_list}
    db_files = repository.workspace.get_all_files_metadata()

    if not languages_in_index:
        requested = parsed_data.get("requested_files") or []
        languages_in_index = {LanguageRegistry.detect_language(fp) or "unknown" for fp in requested}
        if not languages_in_index and project_root:
            try:
                from engines.scip.wrapper import detect_languages
                languages_in_index = set(detect_languages(project_root))
            except Exception:
                pass
        if not languages_in_index:
            languages_in_index = {meta["language"] for meta in db_files.values() if meta.get("language")}

    deleted_files = []
    for fp, meta in db_files.items():
        if meta.get("language") in languages_in_index and fp not in files_to_register:
            exists_on_disk = False
            try:
                exists_on_disk = (project_root / fp).exists() if project_root else Path(fp).exists()
            except Exception:
                pass
            if not exists_on_disk and (project_root is not None or Path(fp).is_absolute()):
                deleted_files.append(fp)

    changed_files: List[str] = []
    unchanged_files: List[str] = []
    if is_partial:
        # Partial parse was already scoped (including dependents) before parse_index()
        changed_files = file_list
    elif project_root and not force:
        for fp in file_list:
            current_hash = calculate_sha256(project_root / fp)
            db_hash = db_files.get(fp, {}).get("sha256", "")
            if current_hash != db_hash:
                changed_files.append(fp)
            else:
                unchanged_files.append(fp)

        if changed_files:
            changed_files = list(
                expand_changed_files(repository, changed_files, new_symbols=parsed_data.get("symbols"), max_depth=1)
            )
            logger.info(
                "[SCIP Ingest] Incremental: %d to process (including dependents), %d unchanged",
                len(changed_files),
                len(unchanged_files),
            )
    else:
        changed_files = file_list

    # Full-repo Shrink Guard applies strictly to complete workspace parses, never partial dirty-file syncs
    if not is_partial and not force and not unchanged_files:
        new_symbols_count = sum(1 for v in parsed_data.get("symbols", {}).values() if v.get("filepath"))
        existing_symbols_count = (
            repository.analytics.get_symbol_count_by_languages(list(languages_in_index))
            if languages_in_index
            else 0
        )
        if len(deleted_files) == 0 and existing_symbols_count > 0:
            is_suspicious_shrink = (
                new_symbols_count == 0
                or (new_symbols_count < existing_symbols_count * 0.90 and (existing_symbols_count - new_symbols_count) > 50)
            )
            if is_suspicious_shrink:
                raise ValueError(
                    f"Shrink Guard: New index has {new_symbols_count} symbols, but database has {existing_symbols_count} existing symbols for {languages_in_index}. "
                    "Refusing to overwrite. This might be due to a failed SCIP extraction. Pass force=True to override."
                )

    return file_list, changed_files, unchanged_files, deleted_files, bool(db_files)


def _ingest_files_table(
    repository,
    file_list: List[str],
    deleted_files: List[str],
    project_root: Optional[Path] = None,
):
    """Writes file records to WorkspaceStore and cascades deleted files."""
    if deleted_files:
        for fp in deleted_files:
            logger.info("[SCIP Ingest] Cleaning up deleted file from database: %s", fp)
        repository.delete_files(deleted_files)

    files_to_ingest = [
        {
            "filepath": fp,
            "sha256": calculate_sha256(project_root / fp) if project_root else "initial_hash",
            "language": LanguageRegistry.detect_language(fp) or "unknown",
        }
        for fp in file_list
    ]
    repository.workspace.upsert_files(files_to_ingest)


def _stage_index_data(
    repository,
    parsed_data: Dict[str, Any],
    changed_files: List[str],
) -> Dict[str, Any]:
    """Stages canonical symbols, occurrences, diagnostics, and edges for changed files."""
    changed_set = {fp.replace("\\", "/") for fp in changed_files}
    filtered_symbols = {
        k: {**v, "filepath": v["filepath"].replace("\\", "/") if v.get("filepath") else None}
        for k, v in parsed_data.get("symbols", {}).items()
        if v.get("filepath") is None or v["filepath"].replace("\\", "/") in changed_set
    }
    logger.info("[SCIP Ingest] Staging %d symbols from %d changed files...", len(filtered_symbols), len(changed_files))

    existing_symbols: Dict[str, Dict[str, Any]] = {}
    if changed_files:
        for sdata in repository.graph.get_symbols_for_files(list(changed_set)):
            existing_symbols[sdata["symbol"]] = sdata

    symbols_to_ingest = [
        {
            "symbol": sym["symbol"],
            "name": sym.get("name") or parse_canonical_id(sym["symbol"])[2] or sym["symbol"],
            "scip_id": sym.get("scip_id"),
            "filepath": sym.get("filepath"),
            "kind": sym.get("kind"),
            "signature": sym.get("signature"),
            "docstring": sym.get("docstring"),
            "body_hash": sym.get("body_hash"),
            "parent_symbol": sym.get("parent_symbol"),
            "start_line": sym.get("start_line"),
            "start_col": sym.get("start_col"),
            "end_line": sym.get("end_line"),
            "end_col": sym.get("end_col"),
        }
        for sym in filtered_symbols.values()
    ]

    filtered_occurrences = [
        {**occ, "filepath": occ["filepath"].replace("\\", "/")}
        for occ in parsed_data.get("occurrences", [])
        if occ.get("filepath") and occ["filepath"].replace("\\", "/") in changed_set
    ]

    filtered_diagnostics = [
        {**d, "filepath": d["filepath"].replace("\\", "/")}
        for d in parsed_data.get("diagnostics", [])
        if d.get("filepath") and d["filepath"].replace("\\", "/") in changed_set
    ]

    edges_to_ingest = [
        {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
            "weight": 1.0,
            "call_line": edge.get("call_line"),
        }
        for edge in parsed_data.get("edges", [])
        if (filtered_symbols.get(edge["source"], {}).get("filepath") or "").replace("\\", "/") in changed_set
        or (filtered_symbols.get(edge["target"], {}).get("filepath") or "").replace("\\", "/") in changed_set
    ]

    return {
        "changed_set": changed_set,
        "filtered_symbols": filtered_symbols,
        "existing_symbols": existing_symbols,
        "symbols_to_ingest": symbols_to_ingest,
        "occurrences_to_ingest": filtered_occurrences,
        "diagnostics_to_ingest": filtered_diagnostics,
        "edges_to_ingest": edges_to_ingest,
    }


def _cleanup_stale_records(
    repository,
    changed_files: List[str],
    force: bool,
    staged_data: Dict[str, Any],
):
    """Deletes stale edges, occurrences, diagnostics, and removed symbols inside the active transaction."""
    t0 = time.perf_counter()
    filtered_symbols = staged_data["filtered_symbols"]
    existing_symbols = staged_data["existing_symbols"]
    changed_set = staged_data["changed_set"]

    if force:
        repository.graph.delete_edges(filepaths=changed_files, exclude_relations=["Injects", "FFI_Binds"])
        repository.graph.delete_occurrences(changed_files)
        repository.quality.delete_diagnostics(changed_files)
        repository.graph.delete_symbols(filepaths=changed_files)
    elif changed_files:
        repository.graph.delete_edges(filepaths=changed_files, exclude_relations=["Injects", "FFI_Binds"])
        repository.graph.delete_occurrences(changed_files)
        repository.quality.delete_diagnostics(changed_files)
        removed_symbols = [
            sym_id
            for sym_id, sym in existing_symbols.items()
            if sym.get("filepath") in changed_set and sym_id not in filtered_symbols
        ]
        if removed_symbols:
            repository.graph.delete_symbols(symbols=removed_symbols)

    t_clean = time.perf_counter() - t0
    if t_clean > 0.05:
        logger.info("[SCIP Ingest] Cleanup completed in %.3fs", t_clean)


def _write_index_batches(
    repository,
    staged_data: Dict[str, Any],
    changed_files: List[str],
    force: bool = False,
    had_existing_files: bool = True,
):
    """Performs transactional cleanup and bulk writes for symbols, occurrences, diagnostics, and edges."""
    symbols_to_ingest = staged_data["symbols_to_ingest"]
    chunk_size = 10_000

    with repository.transaction():
        _cleanup_stale_records(repository, changed_files, force, staged_data)

        for i in range(0, len(symbols_to_ingest), chunk_size):
            repository.graph.upsert_semantic_symbols(symbols_to_ingest[i:i + chunk_size])

        filtered_occurrences = staged_data["occurrences_to_ingest"]
        for i in range(0, len(filtered_occurrences), chunk_size):
            repository.graph.upsert_occurrences(filtered_occurrences[i:i + chunk_size])

        filtered_diagnostics = staged_data["diagnostics_to_ingest"]
        if filtered_diagnostics:
            repository.quality.upsert_diagnostics(filtered_diagnostics)

        edges_to_ingest = staged_data["edges_to_ingest"]
        for i in range(0, len(edges_to_ingest), chunk_size):
            repository.graph.upsert_edges(edges_to_ingest[i:i + chunk_size])

        if force and had_existing_files:
            orphaned_edges, orphaned_occurrences = repository.graph.delete_orphaned_records()
            if orphaned_edges or orphaned_occurrences:
                logger.info(
                    "[SCIP Ingest] Cleaned up %d orphaned edges, %d orphaned occurrences",
                    orphaned_edges,
                    orphaned_occurrences,
                )

        repository.graph.recalculate_connection_weights()


def ingest_index(
    repository,
    parsed_data: Dict[str, Any],
    project_root: Optional[Path] = None,
    force: bool = False,
):
    """Incrementally ingests parsed canonical SCIP symbols, occurrences, diagnostics, and edges."""
    file_list, changed_files, _, deleted_files, had_existing_files = _resolve_changed_and_deleted(
        repository, parsed_data, project_root, force
    )
    _ingest_files_table(repository, file_list, deleted_files, project_root)

    if not changed_files and not deleted_files:
        logger.info("[SCIP Ingest] No files changed. Skipping symbol/occurrence/edge ingestion.")
        return

    staged_data = _stage_index_data(repository, parsed_data, changed_files)
    _write_index_batches(repository, staged_data, changed_files, force, had_existing_files=had_existing_files)
    logger.info("[SCIP Ingest] Ingestion complete.")
