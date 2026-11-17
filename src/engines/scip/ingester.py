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
        files_to_register = set()
        for f in parsed_data.get("files", []):
            if f:
                files_to_register.add(f.replace("\\", "/"))
        for occ in parsed_data["occurrences"]:
            if occ.get("filepath"):
                files_to_register.add(occ["filepath"].replace("\\", "/"))
        for sym in parsed_data["symbols"].values():
            if sym.get("filepath"):
                files_to_register.add(sym["filepath"].replace("\\", "/"))

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
                invalidator = TransitiveInvalidation(repository, max_depth=1)
                changed_files = list(invalidator.expand_changed_files(changed_files, new_symbols=parsed_data.get("symbols")))
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

        if deleted_files:
            for fp in deleted_files:
                print(f"[SCIP Ingest] Cleaning up deleted file from database: {fp}")
            from db.cascade import CascadeCleanupService
            CascadeCleanupService(repository).delete_files_bulk(deleted_files)

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

        # 2. Ingest symbols (only changed files + all external symbols)
        changed_set = {fp.replace("\\", "/") for fp in changed_files}
        filtered_symbols = {
            k: {**v, "filepath": v["filepath"].replace("\\", "/") if v.get("filepath") else None}
            for k, v in parsed_data["symbols"].items()
            if v.get("filepath") is None or v["filepath"].replace("\\", "/") in changed_set
        }
        total_symbols = len(filtered_symbols)
        print(f"[SCIP Ingest] Ingesting {total_symbols} symbols from {len(changed_files)} changed files...")

        existing_symbols = {}
        existing_by_clean = {}
        from utils.helpers import demangle_scip_symbol
        if changed_files:
            existing_symbols = repository.symbols.get_symbols_by_filepaths(list(changed_set))
            for sid, sdata in existing_symbols.items():
                fp = sdata.get("filepath")
                csym = sdata.get("clean_symbol") or sid
                if fp and csym:
                    existing_by_clean[(fp, csym)] = sdata

        # 1b. Delete old edges, symbols, and occurrences for changed files before re-ingesting.
        # Order matters: edges first, then occurrences, then symbols.
        if force:
            repository.edges.delete_edges_for_files(changed_files)
            repository.symbols.delete_occurrences_for_files(changed_files)
            repository.symbols.delete_diagnostics_for_files(changed_files)
            repository.symbols.delete_symbols_for_files(changed_files)
        elif changed_files:
            repository.edges.delete_edges_for_files(changed_files)
            repository.symbols.delete_occurrences_for_files(changed_files)
            repository.symbols.delete_diagnostics_for_files(changed_files)
            upgraded_clean = {
                (v["filepath"], demangle_scip_symbol(k))
                for k, v in filtered_symbols.items() if v.get("filepath")
            }
            removed_symbols = [
                sym_id for sym_id, sym in existing_symbols.items()
                if (not sym.get("filepath") or sym.get("filepath") in changed_set)
                and sym_id not in filtered_symbols
                and (sym.get("filepath"), sym.get("clean_symbol") or sym_id) not in upgraded_clean
            ]
            if removed_symbols:
                with repository.db_conn.session() as conn:
                    conn.execute(
                        "DELETE FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
                        (removed_symbols,)
                    )

        symbols_to_ingest = []
        for sym_id, sym in filtered_symbols.items():
            existing = existing_symbols.get(sym_id)
            if not existing and sym.get("filepath"):
                clean = demangle_scip_symbol(sym["symbol"])
                existing = existing_by_clean.get((sym["filepath"], clean))

            sig = sym.get("signature")
            doc = sym.get("docstring")
            parent_sym = sym.get("parent_symbol")
            code_block = sym.get("code_block")
            if existing:
                # Prioritize existing high-fidelity Tree-sitter signatures and docstrings
                if existing.get("signature"):
                    sig = existing["signature"]
                if existing.get("docstring"):
                    doc = existing["docstring"]
                if existing.get("parent_symbol") and not parent_sym:
                    parent_sym = existing["parent_symbol"]
                if existing.get("code_block") and not code_block:
                    code_block = existing["code_block"]

            if not existing or (
                existing.get("body_hash") != sym.get("body_hash")
                or existing.get("kind") != sym.get("kind")
                or (sig and existing.get("signature") != sig)
                or (doc and existing.get("docstring") != doc)
                or (parent_sym and existing.get("parent_symbol") != parent_sym)
                or (code_block and existing.get("code_block") != code_block)
            ):
                symbols_to_ingest.append({
                    "symbol": sym["symbol"],
                    "clean_symbol": demangle_scip_symbol(sym["symbol"]),
                    "filepath": sym["filepath"],
                    "kind": sym["kind"],
                    "signature": sig,
                    "docstring": doc,
                    "body_hash": sym["body_hash"],
                    "parent_symbol": parent_sym,
                    "code_block": code_block,
                })

        skipped = total_symbols - len(symbols_to_ingest)
        if skipped > 0:
            print(f"  Skipped {skipped} unchanged symbols.")
        print(f"[SCIP Ingest] Writing {len(symbols_to_ingest)} symbols to database...")
        sym_chunk = 10_000
        for i in range(0, len(symbols_to_ingest), sym_chunk):
            chunk = symbols_to_ingest[i:i + sym_chunk]
            repository.symbols.upsert_symbols_bulk(chunk)
            print_progress(min(i + sym_chunk, len(symbols_to_ingest)), len(symbols_to_ingest), prefix="[SCIP Ingest] Symbols DB")

        # 3. Ingest occurrences (only changed files)
        filtered_occurrences = [
            {**occ, "filepath": occ["filepath"].replace("\\", "/")}
            for occ in parsed_data["occurrences"]
            if occ.get("filepath") and occ["filepath"].replace("\\", "/") in changed_set
        ]
        total_occ = len(filtered_occurrences)
        print(f"[SCIP Ingest] Ingesting {total_occ} occurrences...")
        occ_chunk = 10_000
        for i in range(0, total_occ, occ_chunk):
            chunk = filtered_occurrences[i:i + occ_chunk]
            repository.symbols.add_occurrences_bulk(chunk)
            print_progress(min(i + occ_chunk, total_occ), total_occ, prefix="[SCIP Ingest] Occurrences")

        # 3b. Ingest diagnostics (only changed files)
        filtered_diagnostics = [
            {**d, "filepath": d["filepath"].replace("\\", "/")}
            for d in parsed_data.get("diagnostics", [])
            if d.get("filepath") and d["filepath"].replace("\\", "/") in changed_set
        ]
        if filtered_diagnostics:
            print(f"[SCIP Ingest] Ingesting {len(filtered_diagnostics)} diagnostics...")
            repository.symbols.add_diagnostics_bulk(filtered_diagnostics)

        # 4. Ingest call graph edges (only changed files)
        filtered_edges = [
            e for e in parsed_data["edges"]
            if (filtered_symbols.get(e["source"], {}).get("filepath") or "").replace("\\", "/") in changed_set
            or (filtered_symbols.get(e["target"], {}).get("filepath") or "").replace("\\", "/") in changed_set
        ]
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
        if force:
            orphaned_edges = repository.edges.delete_orphaned_edges()
            orphaned_occurrences = repository.symbols.delete_orphaned_occurrences()
            if orphaned_edges or orphaned_occurrences:
                print(f"[SCIP Ingest] Cleaned up {orphaned_edges} orphaned edges, {orphaned_occurrences} orphaned occurrences")

        # 6. Recalculate connection weights for symbols
        print("[SCIP Ingest] Recalculating symbol connection weights...")
        repository.symbols.recalculate_connection_weights()

        print("[SCIP Ingest] Ingestion complete.")
