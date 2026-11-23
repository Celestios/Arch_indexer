"""Incremental SCIP semantic ingestion into DuckDB with disjoint Tier-2 ownership."""
import time
import collections
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from engines.scip.utils import print_progress
from engines.reconciler import reconcile_symbol_id
from utils.helpers import ext_to_lang, demangle_scip_symbol
from change_tracker.tracker import calculate_sha256
from change_tracker.invalidation import expand_changed_files


def _resolve_changed_and_deleted(
    repository,
    parsed_data: Dict[str, Any],
    project_root: Optional[Path] = None,
    force: bool = False,
) -> Tuple[List[str], List[str], List[str], List[str], bool]:
    """Resolves changed files, deleted files, unchanged files, and hashes."""
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

    languages_in_index = {ext_to_lang(Path(fp).suffix.lower()) for fp in file_list}
    db_files = repository.workspace.get_all_files_metadata()

    if not languages_in_index:
        if project_root:
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

    changed_files = []
    unchanged_files = []
    if project_root and not force:
        for fp in file_list:
            current_hash = calculate_sha256(project_root / fp)
            db_hash = db_files.get(fp, {}).get("sha256", "")
            if current_hash != db_hash:
                changed_files.append(fp)
            else:
                unchanged_files.append(fp)

        if changed_files:
            changed_files = list(expand_changed_files(repository, changed_files, new_symbols=parsed_data.get("symbols"), max_depth=1))
            print(f"[SCIP Ingest] Incremental: {len(changed_files)} to process (including dependents), {len(unchanged_files)} unchanged")
    else:
        changed_files = file_list

    if force or not unchanged_files:
        new_symbols_count = sum(1 for v in parsed_data.get("symbols", {}).values() if v.get("filepath"))
        existing_symbols_count = (
            repository.analytics.get_symbol_count_by_languages(list(languages_in_index))
            if languages_in_index
            else 0
        )
        if not force and len(deleted_files) == 0 and existing_symbols_count > 0:
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
            print(f"[SCIP Ingest] Cleaning up deleted file from database: {fp}")
        repository.delete_files(deleted_files)

    files_to_ingest = [
        {
            "filepath": fp,
            "sha256": calculate_sha256(project_root / fp) if project_root else "initial_hash",
            "language": ext_to_lang(Path(fp).suffix.lower()),
        }
        for fp in file_list
    ]
    repository.workspace.upsert_files(files_to_ingest)


def _reconcile_and_stage_symbols(
    repository,
    parsed_data: Dict[str, Any],
    changed_files: List[str],
) -> Dict[str, Any]:
    """Reconciles Tier-2 SCIP symbols against existing Tier-1 syntactic rows and stages semantic batches."""
    changed_set = {fp.replace("\\", "/") for fp in changed_files}
    filtered_symbols = {
        k: {**v, "filepath": v["filepath"].replace("\\", "/") if v.get("filepath") else None}
        for k, v in parsed_data.get("symbols", {}).items()
        if v.get("filepath") is None or v["filepath"].replace("\\", "/") in changed_set
    }
    print(f"[SCIP Ingest] Ingesting {len(filtered_symbols)} symbols from {len(changed_files)} changed files...")

    existing_symbols: Dict[str, Dict[str, Any]] = {}
    clean_to_existing_by_fp: Dict[str, Dict[str, str]] = collections.defaultdict(dict)
    line_to_existing_by_fp: Dict[str, Dict[int, str]] = collections.defaultdict(dict)
    coords_by_fp: Dict[str, List[Tuple[str, int]]] = collections.defaultdict(list)

    if changed_files:
        for sdata in repository.graph.get_symbols_for_files(list(changed_set)):
            sid = sdata["symbol"]
            existing_symbols[sid] = sdata
            fp = sdata.get("filepath")
            csym = sdata.get("clean_symbol") or sid
            if fp and csym:
                clean_to_existing_by_fp[fp][csym] = sid
            s_line = sdata.get("start_line")
            if fp and s_line is not None:
                line_to_existing_by_fp[fp][s_line] = sid
                coords_by_fp[fp].append((sid, s_line))

    symbols_to_ingest = []
    superseded_ids = set()
    reconciled_id_map = {}

    for sym_id, sym in filtered_symbols.items():
        sym_fp = sym.get("filepath")
        clean = demangle_scip_symbol(sym["symbol"])
        existing_id = sym_id if sym_id in existing_symbols else None

        if existing_id is None and sym_fp:
            existing_id = reconcile_symbol_id(
                clean_symbol=clean,
                start_line=sym.get("start_line"),
                clean_to_existing=clean_to_existing_by_fp.get(sym_fp, {}),
                line_to_existing=line_to_existing_by_fp.get(sym_fp, {}),
                occ_list=coords_by_fp.get(sym_fp, []),
            )
            if existing_id and existing_id != sym_id:
                superseded_ids.add(existing_id)
                reconciled_id_map[existing_id] = sym_id

        # Tier-1 owns syntactic fields when a Tier-1 record was upgraded to a SCIP symbol ID.
        # UPSERT_SEMANTIC_SYMBOL_SQL guarantees existing syntactic columns are never clobbered.
        upgraded = existing_symbols.get(existing_id) if (existing_id and existing_id != sym_id) else None
        symbols_to_ingest.append({
            "symbol": sym["symbol"],
            "clean_symbol": clean,
            "filepath": sym_fp,
            "kind": (upgraded.get("kind") if upgraded and upgraded.get("kind") != "UnspecifiedKind" else None) or sym.get("kind"),
            "signature": (upgraded.get("signature") if upgraded else None) or sym.get("signature"),
            "docstring": (upgraded.get("docstring") if upgraded else None) or sym.get("docstring"),
            "body_hash": (upgraded.get("body_hash") if upgraded else None) or sym.get("body_hash"),
            "parent_symbol": (upgraded.get("parent_symbol") if upgraded else None) or sym.get("parent_symbol"),
            "start_line": (upgraded.get("start_line") if upgraded else None) or sym.get("start_line"),
            "start_col": upgraded.get("start_col") if (upgraded and upgraded.get("start_col") is not None) else sym.get("start_col"),
            "end_line": (upgraded.get("end_line") if upgraded else None) or sym.get("end_line"),
            "end_col": upgraded.get("end_col") if (upgraded and upgraded.get("end_col") is not None) else sym.get("end_col"),
        })

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
        "superseded_ids": superseded_ids,
        "reconciled_id_map": reconciled_id_map,
        "symbols_to_ingest": symbols_to_ingest,
        "occurrences_to_ingest": filtered_occurrences,
        "diagnostics_to_ingest": filtered_diagnostics,
        "edges_to_ingest": edges_to_ingest,
    }


def _cleanup_superseded_records(
    repository,
    changed_files: List[str],
    force: bool,
    staged_data: Dict[str, Any],
):
    """Deletes stale edges, occurrences, diagnostics, and removed/superseded symbols inside the active transaction."""
    t0 = time.perf_counter()
    filtered_symbols = staged_data.get("filtered_symbols", {})
    existing_symbols = staged_data.get("existing_symbols", {})
    changed_set = staged_data.get("changed_set", {fp.replace("\\", "/") for fp in changed_files})
    superseded_ids = set(staged_data.get("superseded_ids", ()))

    if force:
        repository.graph.delete_edges(filepaths=changed_files, exclude_relations=["Injects", "FFI_Binds"])
        repository.graph.delete_occurrences(changed_files)
        repository.quality.delete_diagnostics(changed_files)
        repository.graph.delete_symbols(filepaths=changed_files)
    elif changed_files:
        repository.graph.delete_edges(filepaths=changed_files, exclude_relations=["Injects", "FFI_Binds"])
        repository.graph.delete_occurrences(changed_files)
        repository.quality.delete_diagnostics(changed_files)
        upgraded_clean = {
            (v["filepath"], demangle_scip_symbol(k))
            for k, v in filtered_symbols.items()
            if v.get("filepath")
        }
        removed_symbols = list(
            superseded_ids
            | {
                sym_id
                for sym_id, sym in existing_symbols.items()
                if sym.get("filepath") in changed_set
                and sym_id not in filtered_symbols
                and (sym.get("filepath"), sym.get("clean_symbol") or sym_id) not in upgraded_clean
            }
        )
        if removed_symbols:
            repository.graph.delete_symbols(symbols=removed_symbols)
    t_clean = time.perf_counter() - t0
    if t_clean > 0.05:
        print(f"[SCIP Ingest] Cleanup completed in {t_clean:.3f}s")


def _write_index_batches(
    repository,
    staged_data: Dict[str, Any],
    changed_files: List[str],
    force: bool = False,
    had_existing_files: bool = True,
):
    """Performs transactional cleanup and bulk writes for symbols, occurrences, diagnostics, and edges."""
    symbols_to_ingest = staged_data["symbols_to_ingest"]
    print(f"[SCIP Ingest] Writing {len(symbols_to_ingest)} symbols to database...")
    chunk_size = 10_000

    with repository.transaction():
        _cleanup_superseded_records(repository, changed_files, force, staged_data)

        for i in range(0, len(symbols_to_ingest), chunk_size):
            repository.graph.upsert_semantic_symbols(symbols_to_ingest[i:i + chunk_size])
            print_progress(min(i + chunk_size, len(symbols_to_ingest)), len(symbols_to_ingest), prefix="[SCIP Ingest] Symbols DB")

        filtered_occurrences = staged_data["occurrences_to_ingest"]
        total_occ = len(filtered_occurrences)
        print(f"[SCIP Ingest] Ingesting {total_occ} occurrences...")
        for i in range(0, total_occ, chunk_size):
            repository.graph.upsert_occurrences(filtered_occurrences[i:i + chunk_size])
            print_progress(min(i + chunk_size, total_occ), total_occ, prefix="[SCIP Ingest] Occurrences")

        filtered_diagnostics = staged_data["diagnostics_to_ingest"]
        if filtered_diagnostics:
            print(f"[SCIP Ingest] Ingesting {len(filtered_diagnostics)} diagnostics...")
            repository.quality.upsert_diagnostics(filtered_diagnostics)

        edges_to_ingest = staged_data["edges_to_ingest"]
        total_edges = len(edges_to_ingest)
        print(f"[SCIP Ingest] Ingesting {total_edges} edges from changed files...")
        for i in range(0, total_edges, chunk_size):
            repository.graph.upsert_edges(edges_to_ingest[i:i + chunk_size])
            print_progress(min(i + chunk_size, total_edges), total_edges, prefix="[SCIP Ingest] Edges")

        reconciled_id_map = staged_data.get("reconciled_id_map", {})
        if reconciled_id_map:
            repository.graph.remap_edge_symbols(reconciled_id_map)

        if force and had_existing_files:
            orphaned_edges, orphaned_occurrences = repository.graph.delete_orphaned_records()
            if orphaned_edges or orphaned_occurrences:
                print(f"[SCIP Ingest] Cleaned up {orphaned_edges} orphaned edges, {orphaned_occurrences} orphaned occurrences")

        print("[SCIP Ingest] Recalculating symbol connection weights...")
        repository.graph.recalculate_connection_weights()


def ingest_index(
    repository,
    parsed_data: Dict[str, Any],
    project_root: Optional[Path] = None,
    force: bool = False,
):
    """Incrementally ingests parsed SCIP symbols, reference occurrences, diagnostics, and edges."""
    file_list, changed_files, _, deleted_files, had_existing_files = _resolve_changed_and_deleted(
        repository, parsed_data, project_root, force
    )
    _ingest_files_table(repository, file_list, deleted_files, project_root)

    if not changed_files and not deleted_files:
        print("[SCIP Ingest] No files changed. Skipping symbol/occurrence/edge ingestion.")
        return

    staged_data = _reconcile_and_stage_symbols(repository, parsed_data, changed_files)
    _write_index_batches(repository, staged_data, changed_files, force, had_existing_files=had_existing_files)
    print("[SCIP Ingest] Ingestion complete.")

