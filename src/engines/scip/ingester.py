import re
import collections
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple

from engines.scip.utils import print_progress
from utils.helpers import ext_to_lang, demangle_scip_symbol
from change_tracker.tracker import ChangeTracker
from engines.reconciler import reconcile_symbol_id

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2


class IndexIngester:
    """Handles incremental ingestion of parsed SCIP data into the database."""

    @classmethod
    def _resolve_changed_and_deleted(
        cls,
        repository,
        parsed_data: Dict[str, Any],
        project_root: Optional[Path] = None,
        force: bool = False,
    ) -> Tuple[List[str], List[str], List[str], List[str]]:
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

        # Identify languages present in the new index and clean up deleted files
        languages_in_index = set()
        for fp in file_list:
            ext = Path(fp).suffix.lower()
            lang = ext_to_lang(ext)
            languages_in_index.add(lang)

        db_files = repository.workspace.get_all_files_metadata()

        if not languages_in_index:
            if project_root:
                try:
                    from engines.scip.wrapper import detect_languages
                    languages_in_index = set(detect_languages(project_root))
                except Exception:
                    pass
            if not languages_in_index:
                for fp, meta in db_files.items():
                    if meta.get("language"):
                        languages_in_index.add(meta.get("language"))

        deleted_files = []
        for fp, meta in db_files.items():
            file_lang = meta.get("language")
            if file_lang in languages_in_index and fp not in files_to_register:
                exists_on_disk = False
                if project_root:
                    try:
                        exists_on_disk = (project_root / fp).exists()
                    except Exception:
                        pass
                else:
                    try:
                        exists_on_disk = Path(fp).exists()
                    except Exception:
                        pass
                if not exists_on_disk and (project_root is not None or Path(fp).is_absolute()):
                    deleted_files.append(fp)

        # Determine which files actually changed (incremental)
        changed_files = []
        unchanged_files = []
        if project_root and not force:
            for fp in file_list:
                abs_path = project_root / fp
                current_hash = ChangeTracker.calculate_sha256(abs_path)
                db_hash = db_files.get(fp, {}).get("sha256", "")
                if current_hash != db_hash:
                    changed_files.append(fp)
                else:
                    unchanged_files.append(fp)

            if changed_files:
                from change_tracker.invalidation import expand_changed_files
                changed_files = list(expand_changed_files(repository, changed_files, new_symbols=parsed_data.get("symbols"), max_depth=1))
                print(f"[SCIP Ingest] Incremental: {len(changed_files)} to process (including dependents), {len(unchanged_files)} unchanged")
        else:
            changed_files = file_list
            unchanged_files = []

        # Safety Check / Shrink Guard (skip for incremental)
        if force or not unchanged_files:
            new_symbols_count = sum(1 for v in parsed_data.get("symbols", {}).values() if v.get("filepath"))
            existing_symbols_count = 0
            langs_tuple = tuple(languages_in_index)
            if langs_tuple:
                existing_symbols_count = repository.analytics.count_symbols_by_languages(list(langs_tuple))

            if not force and len(deleted_files) == 0 and existing_symbols_count > 0:
                is_suspicious_shrink = (
                    new_symbols_count == 0 or (
                        new_symbols_count < existing_symbols_count * 0.90
                        and (existing_symbols_count - new_symbols_count) > 50
                    )
                )
                if is_suspicious_shrink:
                    raise ValueError(
                        f"Shrink Guard: New index has {new_symbols_count} symbols, but database has {existing_symbols_count} existing symbols for {languages_in_index}. "
                        "Refusing to overwrite. This might be due to a failed SCIP extraction. Pass force=True to override."
                    )

        return file_list, changed_files, unchanged_files, deleted_files

    @classmethod
    def _ingest_files_table(
        cls,
        repository,
        file_list: List[str],
        deleted_files: List[str],
        project_root: Optional[Path] = None,
    ):
        """Writes file records to repository.files and cascades deleted files."""
        if deleted_files:
            for fp in deleted_files:
                print(f"[SCIP Ingest] Cleaning up deleted file from database: {fp}")
            repository.delete_files(deleted_files)

        files_to_ingest = []
        for fp in file_list:
            sha256_val = "initial_hash"
            if project_root:
                abs_path = project_root / fp
                sha256_val = ChangeTracker.calculate_sha256(abs_path)

            ext = Path(fp).suffix.lower()
            lang = ext_to_lang(ext)
            files_to_ingest.append({"filepath": fp, "sha256": sha256_val, "language": lang})

        repository.workspace.upsert_files_bulk(files_to_ingest)

    @classmethod
    def _reconcile_and_stage_symbols(
        cls,
        repository,
        parsed_data: Dict[str, Any],
        changed_files: List[str],
    ) -> Dict[str, Any]:
        """Maps SCIP symbols, invokes reconcile_symbol_id, and stages symbol/occurrence/diagnostic/edge records."""
        changed_set = {fp.replace("\\", "/") for fp in changed_files}
        filtered_symbols = {
            k: {**v, "filepath": v["filepath"].replace("\\", "/") if v.get("filepath") else None}
            for k, v in parsed_data.get("symbols", {}).items()
            if v.get("filepath") is None or v["filepath"].replace("\\", "/") in changed_set
        }
        total_symbols = len(filtered_symbols)
        print(f"[SCIP Ingest] Ingesting {total_symbols} symbols from {len(changed_files)} changed files...")

        existing_symbols = {}
        clean_to_existing_by_fp = collections.defaultdict(dict)
        line_to_existing_by_fp = collections.defaultdict(dict)
        occs_by_fp = collections.defaultdict(list)

        if changed_files:
            existing_symbols = repository.graph.get_symbols_by_filepaths(list(changed_set))
            for sid, sdata in existing_symbols.items():
                fp = sdata.get("filepath")
                csym = sdata.get("clean_symbol") or sid
                if fp and csym:
                    clean_to_existing_by_fp[fp][csym] = sid
                s_line = sdata.get("start_line")
                if fp and s_line is not None:
                    line_to_existing_by_fp[fp][s_line] = sid
                    occs_by_fp[fp].append((sid, s_line))
            for fp in changed_set:
                for occ in repository.graph.get_occurrences_for_file(fp):
                    if (occ.get("role", 0) & 1) != 0 and occ.get("symbol"):
                        sid = occ["symbol"]
                        s_line = occ["start_line"]
                        if s_line not in line_to_existing_by_fp[fp]:
                            line_to_existing_by_fp[fp][s_line] = sid
                            occs_by_fp[fp].append((sid, s_line))

        # Map SCIP symbol definition lines from parsed symbols and occurrences
        scip_def_lines = {}
        for sym_id, sym_info in parsed_data.get("symbols", {}).items():
            sym_fp = sym_info.get("filepath")
            sym_line = sym_info.get("start_line")
            if sym_fp and sym_line is not None:
                fp_norm = sym_fp.replace("\\", "/")
                scip_def_lines[(fp_norm, sym_id)] = sym_line

        for occ in parsed_data.get("occurrences", []):
            if (occ.get("role", 0) & 1) != 0 and occ.get("symbol") and occ.get("filepath"):
                fp_norm = occ["filepath"].replace("\\", "/")
                if (fp_norm, occ["symbol"]) not in scip_def_lines:
                    scip_def_lines[(fp_norm, occ["symbol"])] = occ["start_line"]

        symbols_to_ingest = []

        for sym_id, sym in filtered_symbols.items():
            sym_fp = sym.get("filepath")
            existing_id = None
            if sym_id in existing_symbols:
                existing_id = sym_id
            elif sym_fp:
                clean = demangle_scip_symbol(sym["symbol"])
                s_line = scip_def_lines.get((sym_fp, sym_id))
                existing_id = reconcile_symbol_id(
                    clean_symbol=clean,
                    start_line=s_line,
                    clean_to_existing=clean_to_existing_by_fp.get(sym_fp, {}),
                    line_to_existing=line_to_existing_by_fp.get(sym_fp, {}),
                    occ_list=occs_by_fp.get(sym_fp, []),
                )

            existing = existing_symbols.get(existing_id) if existing_id else None

            if existing:
                sig = existing.get("signature") or sym.get("signature")
                doc = existing.get("docstring") or sym.get("docstring")
                parent_sym = existing.get("parent_symbol") or sym.get("parent_symbol")
                body_hash = existing.get("body_hash") or sym.get("body_hash")
                kind = existing.get("kind") or sym.get("kind")
            else:
                sig = sym.get("signature")
                doc = sym.get("docstring")
                parent_sym = sym.get("parent_symbol")
                body_hash = sym.get("body_hash")
                kind = sym.get("kind")

            effective_body_hash = body_hash or sym.get("body_hash")
            if not existing or (
                existing.get("body_hash") != effective_body_hash
                or existing.get("kind") != kind
                or (sig and existing.get("signature") != sig)
                or (doc and existing.get("docstring") != doc)
                or (parent_sym and existing.get("parent_symbol") != parent_sym)
                or (sym.get("start_line") is not None and existing.get("start_line") != sym.get("start_line"))
            ):
                symbols_to_ingest.append({
                    "symbol": sym["symbol"],
                    "clean_symbol": demangle_scip_symbol(sym["symbol"]),
                    "filepath": sym["filepath"],
                    "kind": kind,
                    "signature": sig,
                    "docstring": doc,
                    "body_hash": effective_body_hash,
                    "parent_symbol": parent_sym,
                    "start_line": sym.get("start_line"),
                    "start_col": sym.get("start_col"),
                    "end_line": sym.get("end_line"),
                    "end_col": sym.get("end_col"),
                })

        skipped = total_symbols - len(symbols_to_ingest)
        if skipped > 0:
            print(f"  Skipped {skipped} unchanged symbols.")

        # Occurrences
        filtered_occurrences = [
            {**occ, "filepath": occ["filepath"].replace("\\", "/")}
            for occ in parsed_data.get("occurrences", [])
            if occ.get("filepath") and occ["filepath"].replace("\\", "/") in changed_set
        ]

        # Diagnostics
        filtered_diagnostics = [
            {**d, "filepath": d["filepath"].replace("\\", "/")}
            for d in parsed_data.get("diagnostics", [])
            if d.get("filepath") and d["filepath"].replace("\\", "/") in changed_set
        ]

        # Call graph edges
        filtered_edges = [
            e for e in parsed_data.get("edges", [])
            if (filtered_symbols.get(e["source"], {}).get("filepath") or "").replace("\\", "/") in changed_set
            or (filtered_symbols.get(e["target"], {}).get("filepath") or "").replace("\\", "/") in changed_set
        ]
        edges_to_ingest = []
        for edge in filtered_edges:
            edges_to_ingest.append({
                "source": edge["source"],
                "target": edge["target"],
                "relation": edge["relation"],
                "weight": 1.0,
                "call_line": edge.get("call_line"),
            })

        return {
            "changed_set": changed_set,
            "filtered_symbols": filtered_symbols,
            "existing_symbols": existing_symbols,
            "symbols_to_ingest": symbols_to_ingest,
            "occurrences_to_ingest": filtered_occurrences,
            "diagnostics_to_ingest": filtered_diagnostics,
            "edges_to_ingest": edges_to_ingest,
        }

    @classmethod
    def _cleanup_superseded_records(
        cls,
        repository,
        changed_files: List[str],
        force: bool = False,
        staged_data: Optional[Dict[str, Any]] = None,
    ):
        """Handles forced or incremental deletion of old symbols, occurrences, edges, and diagnostics."""
        filtered_symbols = staged_data.get("filtered_symbols") if staged_data else None
        existing_symbols = staged_data.get("existing_symbols") if staged_data else None
        changed_set = staged_data.get("changed_set") if staged_data else {fp.replace("\\", "/") for fp in changed_files}

        if force:
            repository.graph.delete_edges_for_files(changed_files)
            repository.graph.delete_occurrences_for_files(changed_files)
            repository.quality.delete_diagnostics_for_files(changed_files)
            repository.graph.delete_symbols_for_files(changed_files)
        elif changed_files:
            repository.graph.delete_edges_for_files(changed_files)
            repository.graph.delete_occurrences_for_files(changed_files)
            repository.quality.delete_diagnostics_for_files(changed_files)
            if filtered_symbols is not None and existing_symbols is not None:
                upgraded_clean = {
                    (v["filepath"], demangle_scip_symbol(k))
                    for k, v in filtered_symbols.items() if v.get("filepath")
                }
                removed_symbols = [
                    sym_id for sym_id, sym in existing_symbols.items()
                    if (sym.get("filepath") and sym.get("filepath") in changed_set)
                    and sym_id not in filtered_symbols
                    and (sym.get("filepath"), sym.get("clean_symbol") or sym_id) not in upgraded_clean
                ]
                if removed_symbols:
                    repository.graph.delete_symbols_bulk(removed_symbols)

    @classmethod
    def _write_index_batches(
        cls,
        repository,
        staged_data: Dict[str, Any],
        changed_files: List[str],
        force: bool = False,
    ):
        """Performs transactional cleanup and bulk writes for symbols, occurrences, diagnostics, and edges."""
        symbols_to_ingest = staged_data["symbols_to_ingest"]
        print(f"[SCIP Ingest] Writing {len(symbols_to_ingest)} symbols to database...")
        sym_chunk = 10_000

        with repository.transaction():
            cls._cleanup_superseded_records(repository, changed_files, force, staged_data)

            for i in range(0, len(symbols_to_ingest), sym_chunk):
                chunk = symbols_to_ingest[i:i + sym_chunk]
                repository.graph.upsert_symbols_bulk(chunk)
                print_progress(min(i + sym_chunk, len(symbols_to_ingest)), len(symbols_to_ingest), prefix="[SCIP Ingest] Symbols DB")

            filtered_occurrences = staged_data["occurrences_to_ingest"]
            total_occ = len(filtered_occurrences)
            print(f"[SCIP Ingest] Ingesting {total_occ} occurrences...")
            occ_chunk = 10_000
            for i in range(0, total_occ, occ_chunk):
                chunk = filtered_occurrences[i:i + occ_chunk]
                repository.graph.record_occurrences_bulk(chunk)
                print_progress(min(i + occ_chunk, total_occ), total_occ, prefix="[SCIP Ingest] Occurrences")

            filtered_diagnostics = staged_data["diagnostics_to_ingest"]
            if filtered_diagnostics:
                print(f"[SCIP Ingest] Ingesting {len(filtered_diagnostics)} diagnostics...")
                repository.quality.record_diagnostics_bulk(filtered_diagnostics)

            edges_to_ingest = staged_data["edges_to_ingest"]
            total_edges = len(edges_to_ingest)
            print(f"[SCIP Ingest] Ingesting {total_edges} edges from changed files...")
            for idx, edge in enumerate(edges_to_ingest, 1):
                if idx % 100 == 0 or idx == total_edges:
                    print_progress(idx, total_edges, prefix="[SCIP Ingest] Edges")
            repository.graph.add_edges_bulk(edges_to_ingest)

            if force:
                orphaned_edges = repository.graph.delete_orphaned_edges()
                orphaned_occurrences = repository.graph.delete_orphaned_occurrences()
                if orphaned_edges or orphaned_occurrences:
                    print(f"[SCIP Ingest] Cleaned up {orphaned_edges} orphaned edges, {orphaned_occurrences} orphaned occurrences")

            print("[SCIP Ingest] Recalculating symbol connection weights...")
            repository.graph.recalculate_connection_weights()

    @classmethod
    def ingest_index(
        cls,
        repository,
        parsed_data: Dict[str, Any],
        project_root: Optional[Path] = None,
        force: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Optionally uses an embedder to compute vector representations for symbol docstrings.
        Uses incremental ingestion: only processes files whose content has changed.
        """
        # 1. Resolve changed, unchanged, and deleted files
        file_list, changed_files, unchanged_files, deleted_files = cls._resolve_changed_and_deleted(
            repository, parsed_data, project_root, force
        )

        # 2. Ingest files table and clean up deleted files
        cls._ingest_files_table(repository, file_list, deleted_files, project_root)

        if not changed_files and not deleted_files:
            print("[SCIP Ingest] No files changed. Skipping symbol/occurrence/edge ingestion.")
            return

        # 3. Reconcile symbols and stage records
        staged_data = cls._reconcile_and_stage_symbols(repository, parsed_data, changed_files)

        # 4. Write index batches (including transactional cleanup)
        cls._write_index_batches(repository, staged_data, changed_files, force)

        print("[SCIP Ingest] Ingestion complete.")
