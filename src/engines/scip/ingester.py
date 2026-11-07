import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional

from engines.scip.utils import print_progress
from utils.helpers import ext_to_lang

try:
    from engines import scip_pb2
except ImportError:
    import scip_pb2

src_dir = Path(__file__).resolve().parent.parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
from change_tracker.tracker import ChangeTracker


class IndexIngester:
    """Handles incremental ingestion of parsed SCIP data into the database."""

    @staticmethod
    def ingest_index(repository, parsed_data: Dict[str, Any],
                     project_root: Optional[Path] = None, force: bool = False,
                     config: Optional[Dict[str, Any]] = None):
        """
        Ingests the parsed symbols, occurrences, and edges into the database.
        Optionally uses an embedder to compute vector representations for symbol docstrings.
        Uses incremental ingestion: only processes files whose content has changed.
        """
        from change_tracker.tracker import ChangeTracker

        # 1. Register files first
        files_to_register = set(parsed_data.get("files", []))
        for occ in parsed_data["occurrences"]:
            if occ["filepath"]:
                files_to_register.add(occ["filepath"])
        for sym in parsed_data["symbols"].values():
            if sym["filepath"]:
                files_to_register.add(sym["filepath"])

        file_list = list(files_to_register)

        # Identify languages present in the new index and clean up deleted files
        languages_in_index = set()
        for fp in file_list:
            ext = Path(fp).suffix.lower()
            lang = ext_to_lang(ext)
            languages_in_index.add(lang)

        db_files = repository.files.get_all_files_metadata()

        if not languages_in_index:
            if project_root:
                try:
                    from engines.scip.wrapper import ScipWrapper
                    languages_in_index = set(ScipWrapper.detect_languages(project_root))
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
                if not exists_on_disk:
                    deleted_files.append(fp)

        # 2. Determine which files actually changed (incremental)
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
                from change_tracker.invalidation import TransitiveInvalidation
                invalidator = TransitiveInvalidation(repository, max_depth=2)
                changed_files = list(invalidator.expand_changed_files(changed_files))
                print(f"[SCIP Ingest] Incremental: {len(changed_files)} to process (including dependents), {len(unchanged_files)} unchanged")
        else:
            changed_files = file_list
            unchanged_files = []

        # Safety Check / Shrink Guard (skip for incremental)
        if force or not unchanged_files:
            new_symbols_count = sum(1 for v in parsed_data["symbols"].values() if v["filepath"])
            existing_symbols_count = 0
            langs_tuple = tuple(languages_in_index)
            if langs_tuple:
                with repository.db_conn.session() as conn:
                    if len(langs_tuple) == 1:
                        res = conn.execute(
                            "SELECT COUNT(*) FROM symbols WHERE filepath IN (SELECT filepath FROM files WHERE language = ?)",
                            (langs_tuple[0],)
                        ).fetchone()
                    else:
                        placeholders = ",".join("?" for _ in langs_tuple)
                        res = conn.execute(
                            f"SELECT COUNT(*) FROM symbols WHERE filepath IN (SELECT filepath FROM files WHERE language IN ({placeholders}))",
                            langs_tuple
                        ).fetchone()
                    if res:
                        existing_symbols_count = res[0]

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

        for fp in deleted_files:
            print(f"[SCIP Ingest] Cleaning up deleted file from database: {fp}")
            repository.files.delete_file(fp)

        # Register files in bulk with actual SHA-256 hashes
        files_to_ingest = []
        for fp in file_list:
            sha256_val = "initial_hash"
            if project_root:
                abs_path = project_root / fp
                sha256_val = ChangeTracker.calculate_sha256(abs_path)

            ext = Path(fp).suffix.lower()
            lang = ext_to_lang(ext)
            files_to_ingest.append({"filepath": fp, "sha256": sha256_val, "language": lang})

        repository.files.upsert_files_bulk(files_to_ingest)

        if not changed_files and not deleted_files:
            print("[SCIP Ingest] No files changed. Skipping symbol/occurrence/edge ingestion.")
            return

        # 1b. Delete old edges, symbols, and occurrences for changed files before re-ingesting.
        # Order matters: edges first (delete_edges_for_file uses a subquery against symbols),
        # then occurrences, then symbols.
        for fp in changed_files:
            repository.edges.delete_edges_for_file(fp)
        for fp in changed_files:
            repository.symbols.delete_occurrences_for_file(fp)
        for fp in changed_files:
            repository.symbols.delete_symbols_for_file(fp)

        # 2. Ingest symbols (only changed files + all external symbols)
        changed_set = set(changed_files)
        filtered_symbols = {k: v for k, v in parsed_data["symbols"].items()
                           if v["filepath"] is None or v["filepath"] in changed_set}
        total_symbols = len(filtered_symbols)
        print(f"[SCIP Ingest] Ingesting {total_symbols} symbols from {len(changed_files)} changed files...")

        existing_symbols = {}
        if changed_files:
            existing_symbols = repository.symbols.get_symbols_by_filepaths(changed_files)

        symbols_to_ingest = [
            {
                "symbol": sym["symbol"],
                "filepath": sym["filepath"],
                "kind": sym["kind"],
                "signature": sym["signature"],
                "docstring": sym["docstring"],
                "body_hash": sym["body_hash"],
            }
            for sym_id, sym in filtered_symbols.items()
            if sym_id not in existing_symbols or (
                existing_symbols[sym_id]["body_hash"] != sym["body_hash"]
                or existing_symbols[sym_id]["kind"] != sym["kind"]
                or existing_symbols[sym_id]["signature"] != sym.get("signature")
                or existing_symbols[sym_id]["docstring"] != sym["docstring"]
            )
        ]

        skipped = total_symbols - len(symbols_to_ingest)
        if skipped > 0:
            print(f"  Skipped {skipped} unchanged symbols.")
        print(f"[SCIP Ingest] Writing {len(symbols_to_ingest)} symbols to database...")
        sym_chunk = 100
        for i in range(0, len(symbols_to_ingest), sym_chunk):
            chunk = symbols_to_ingest[i:i + sym_chunk]
            repository.symbols.upsert_symbols_bulk(chunk)
            print_progress(min(i + sym_chunk, len(symbols_to_ingest)), len(symbols_to_ingest), prefix="[SCIP Ingest] Symbols DB")

        # 3. Ingest occurrences (only changed files)
        filtered_occurrences = [occ for occ in parsed_data["occurrences"]
                                if occ["filepath"] and occ["filepath"] in changed_set]
        total_occ = len(filtered_occurrences)
        print(f"[SCIP Ingest] Ingesting {total_occ} occurrences...")
        occ_chunk = 100
        for i in range(0, total_occ, occ_chunk):
            chunk = filtered_occurrences[i:i + occ_chunk]
            repository.symbols.add_occurrences_bulk(chunk)
            print_progress(min(i + occ_chunk, total_occ), total_occ, prefix="[SCIP Ingest] Occurrences")

        # 4. Ingest call graph edges (only changed files)
        filtered_edges = [e for e in parsed_data["edges"]
                          if filtered_symbols.get(e["source"], {}).get("filepath") in changed_set
                          or filtered_symbols.get(e["target"], {}).get("filepath") in changed_set]
        total_edges = len(filtered_edges)
        print(f"[SCIP Ingest] Ingesting {total_edges} edges from changed files...")

        if config is None:
            config = {}
            if project_root:
                config_path = project_root / ".arch" / "config.json"
                if config_path.exists():
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                    except Exception:
                        pass

        from engines.scip.wrapper import ScipWrapper

        edges_to_ingest = []
        for idx, edge in enumerate(filtered_edges, 1):
            caller_sym = edge["source"]
            callee_sym = edge["target"]
            caller_fp = parsed_data["symbols"].get(caller_sym, {}).get("filepath")
            callee_fp = parsed_data["symbols"].get(callee_sym, {}).get("filepath")

            weight = ScipWrapper.calculate_edge_weight(caller_fp, callee_fp, config)
            edges_to_ingest.append({
                "source": caller_sym,
                "target": callee_sym,
                "relation": edge["relation"],
                "weight": weight
            })
            if idx % 100 == 0 or idx == total_edges:
                print_progress(idx, total_edges, prefix="[SCIP Ingest] Edges")

        repository.edges.add_edges_bulk(edges_to_ingest)

        # 5. Clean up any orphaned edges and occurrences left over from prior index runs
        orphaned_edges = repository.edges.delete_orphaned_edges()
        orphaned_occurrences = repository.symbols.delete_orphaned_occurrences()
        if orphaned_edges or orphaned_occurrences:
            print(f"[SCIP Ingest] Cleaned up {orphaned_edges} orphaned edges, {orphaned_occurrences} orphaned occurrences")

        # 6. Recalculate connection weights for symbols
        print("[SCIP Ingest] Recalculating symbol connection weights...")
        repository.symbols.recalculate_connection_weights()

        print("[SCIP Ingest] Ingestion complete.")
