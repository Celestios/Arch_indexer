# Dual-Engine Architecture & Responsibility Division

## Decoupling Tree-sitter AST engine from SCIP semantic compiler with two-tier watcher

**Id:** 8ac38053-84f7-4363-82bb-65064874709f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** a unified LSP/compiler infrastructure provides sub-2ms syntactic declaration and range sync alongside cross-file type-checked call graphs

Code intelligence is decoupled into two complementary execution engines with distinct cognitive responsibilities and latency profiles:

1. **Tree-sitter AST Engine (`src/engines/treesitter/`)**: Runs in-process, file-locally, and error-tolerantly with sub-2ms execution time. It has sole responsibility for live line-range coordinates, multi-line declaration signatures, clean docstrings, enclosing parent scopes, skeleton code folding, structural metrics (cyclomatic complexity, nesting depth, LOC), and syntax anti-pattern checks (bare `except:`, `eval()`, `.unwrap()`).
2. **SCIP Semantic Engine (`src/engines/scip/`)**: Runs out-of-process via language compilers/indexers (`scip-python`, `rust-analyzer`, etc.) scoped to package/crate roots. It has sole responsibility for workspace-wide cross-file call graphs (`edges`), trait/interface implementation mappings, type inference, read vs. write state mutation bitmasks, compiler diagnostics (`diagnostics`), and test-to-production reverse coverage.

In `src/change_tracker/watcher.py`, these engines are decoupled into a two-tier pipeline:
- **Tier 1 (Immediate, < 2ms)**: Directly inside `Handler.on_any_event()`, `TreesitterEngine.sync_file_to_db()` parses modified source files and syncs declarations, exact signatures, docstrings, and definition occurrences (`role = 1`) instantly on file save.
- **Tier 2 (Debounced ~3.0s)**: A background debounce timer aggregates dirty package targets and executes the compiler-based SCIP indexer to resolve cross-file edges, reference occurrences, compiler diagnostics, and FFI bridges, followed by the Auditor.

**Reason:** Compiler-based semantic indexers (SCIP) require full type checking across entire packages, taking seconds per run. Running them synchronously on every keystroke or save freezes watcher responsiveness and fails whenever files contain temporary syntax errors during editing. Tree-sitter executes in sub-millisecond time, is completely error-tolerant to incomplete syntax, and provides exact multi-line signatures and docstrings.

**Rejected alternative (SCIP-only indexing):** Relying solely on SCIP for all metadata was the legacy approach. It caused latency bottlenecks, could not sync line coordinates immediately on save, produced broken single-line slices for multi-line signatures, and failed to operate when code had temporary syntax errors or uninstalled toolchains.

**Rejected alternative (Tree-sitter-only indexing):** Relying solely on Tree-sitter AST parsing was rejected because ASTs are file-local. AST pattern matching cannot resolve cross-file import aliases, dynamic trait/interface dispatch, transitively inferred types, or compiler diagnostics without reimplementing full language type checkers.

---

## Protobuf range normalization bug, database protection, and Windows path normalization

**Id:** de4bb3bb-4f58-4368-80ef-d7b32c24efa1
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** incident investigation, 2026-11-17
**Revisit when:** SCIP protocol specification deprecates legacy occurrence range fields entirely in favor of typed_range oneof

A critical bug caused symbols across the workspace (such as `db.connection.DbConnection`) to report signature `import sys` and all occurrences at line 1 (`L1`):

1. **Protobuf `normalize_range` collapse**: In `src/engines/scip/parser.py`, `normalize_range()` checked `getattr(occ, "single_line_range", None) is not None`. Because Protobuf in Python returns default empty submessage instances rather than `None`, integer fields (`line`, `start_character`, `end_character`) defaulted to `0`. `_is_int(0)` returned `True`, collapsing all occurrence coordinates to `(0, 0, 0, 0)` (1-indexed line 1). Ad-hoc text slicing then read line 1 of the file (`import sys` in `src/db/connection.py`).
   - *Fix*: Switched to explicit `occ.HasField("single_line_range")` and `occ.HasField("multi_line_range")`, allowing legacy `occ.range` (which held `[8, 6, 18]` for line 9) to resolve correctly.
2. **Database overwrite protection**: `UPSERT_SYMBOL_SQL` in `src/db/base.py` and `IndexIngester` in `src/engines/scip/ingester.py` were updated with conditional SQL (`CASE WHEN excluded.signature IS NOT NULL AND excluded.signature <> '' THEN excluded.signature ELSE symbols.signature END`) so that subsequent SCIP compilation passes do not overwrite rich Tree-sitter signatures and docstrings.
3. **Windows path normalization in ingester**: On Windows, SCIP occurrences and edges contained backslash paths (`src\\main.py`), while `changed_set` contained normalized forward slashes (`src/main.py`), causing occurrences and edges to be filtered out during ingestion. Normalized all paths to forward slashes in `IndexIngester`.

**Reason:** Eliminating range collapse restores accurate occurrence coordinates and call graph caller mappings. Protecting database symbol metadata ensures the two engines cooperate without data clobbering.

---

## Tree-sitter Dart parser integration and path-inclusion normalization

**Id:** 5c8e3101-9a72-4cf4-9de2-984e7be0f81d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session, 2026-11-18
**Revisit when:** Tree-sitter upstream provides native unified multi-language loaders without separate per-language binary packages

Tree-sitter AST parsing was extended to support Dart via `tree-sitter-dart>=0.1.0`, and file traversal filtering in `TreesitterEngine.sync_project_to_db` was refactored from ad-hoc path string checks to `is_included()` and `is_excluded()` from `utils.exclusions`.

**Reason:** In Flutter/Dart codebases, Tree-sitter previously extracted 0 symbols because `tree-sitter-dart` was absent from dependencies. Furthermore, when `.arch/config.json` contained directory prefixes with trailing slashes (e.g. `"lib/"`), raw substring comparisons (`part in include_dirs`) failed to match path segments (`"lib"`), causing Tree-sitter to silently skip all workspace files.

---

## Decoupled Tier-1 (Tree-sitter) and Tier-2 (SCIP) file modification hashes to prevent change detection poisoning

**Id:** b06e7f5d-a73c-477c-83a8-f92cdbeabee7
**Type:** incident
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session and bug investigation, 2026-11-23
**Revisit when:** Tree-sitter and SCIP indexing pipelines are unified into a single single-pass compiler engine

In `src/db/schema.sql` (schema version 3), the `files` table was extended with a separate `ast_sha256 VARCHAR DEFAULT ''` column, decoupling Tier-1 syntactic file hashes from Tier-2 semantic compiler hashes (`files.sha256`). `sync_file_to_db` in `src/engines/treesitter/` updates `ast_sha256` exclusively via `upsert_ast_file`, leaving `files.sha256` untouched.

**Reason:** In `sync_workspace`, Tier-1 Tree-sitter runs immediately before Tier-2 SCIP. Previously, `sync_file_to_db` wrote the file's current disk SHA-256 directly to `files.sha256`. When Tier-2 SCIP ingester subsequently checked for modified files via `_resolve_changed_and_deleted`, `current_hash == db_hash` evaluated to `True` for every file that Tree-sitter had parsed. As a result, all successfully parsed source files (505 out of 506 Dart files in Flutter workspaces) were categorized as unchanged and dropped from `changed_files`. SCIP symbols, occurrences, and edges were never ingested, leaving the database stuck with incomplete syntactic dotted symbol stubs and 0 call graph edges. Decoupling the hash columns ensures Tier-1 AST extraction never poisons Tier-2 semantic change detection.

**Rejected alternative:** Bypassing change detection by forcing `force=True` on every run was rejected because it causes full workspace re-indexing on every incremental change, destroying sub-second watcher turnaround.

---

## Reconciling Tier-1 Injects edges to canonical Tier-2 SCIP symbol IDs

**Id:** 7a90adc0-00e9-4c7d-bb3a-95f2cbe860b5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session and architecture decision, 2026-11-23
**Revisit when:** Riverpod/DI frameworks provide native SCIP indexer relationship output

In `src/engines/scip/ingester.py` and `src/db/store_graph.py`, `_reconcile_and_stage_symbols` builds a `reconciled_id_map: Dict[str, str]` tracking every Tier-1 Tree-sitter symbol ID upgraded to a canonical SCIP symbol ID. Before running orphan cleanup, `_write_index_batches` calls `repository.graph.remap_edge_symbols(reconciled_id_map)` to update `edges.source` and `edges.target` to the upgraded SCIP IDs.

**Reason:** Tier-1 AST dependency injection analyzers (e.g. Flutter Riverpod / Provider) extract `Injects` edges using file-local Tree-sitter symbol IDs (e.g. `features.graph.ui.canvas.graph_canvas._GraphCanvasState`). When Tier-2 SCIP runs, these symbols are reconciled and upgraded to canonical package-qualified SCIP IDs (`scip-dart pub ...`), and stale Tree-sitter IDs are deleted. Without symbol remapping on edges, `delete_orphaned_records` purged all `Injects` edges because their endpoints no longer existed in `symbols`, or left them disconnected with `src_lang = 'external'`. Remapping endpoints preserves DI architecture links and integrates them directly into the full cross-file call graph.

**Rejected alternative:** Keeping duplicate Tree-sitter symbol rows in `symbols` alongside SCIP symbols was rejected because it produces fragmented duplicate symbols, confuses symbol lookup tools, and breaks 1:1 symbol coordinate mappings.

**Rejected alternative (SCIP-only indexing for Dart):** Relying solely on `scip-dart` without Tree-sitter was rejected because SCIP lacks sub-millisecond AST synchronization on file save and cannot extract multi-line signatures or docstrings in real time when files contain transient syntax errors.

---

## Weighted hybrid Tier-2 SCIP gate, 2.5h max-age timer, and crash-safe pending queue

**Id:** 33c75ea2-db59-423a-a807-24adb1cc3868
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session, 2026-11-25
**Revisit when:** incremental SCIP compilers (e.g., `rust-analyzer scip` / `scip_dart`) complete in under a few seconds per edit

Tier-1 Tree-sitter AST synchronization still runs immediately on every Watchdog file event, while Tier-2 SCIP re-indexing in `src/change_tracker/watcher_manager.py` is gated by a weighted hybrid trigger:
- **Weighted score (`>= 3500` after `10.0s` coalesce)**: `5 * files + 1 * line_delta + 10 * ast_changed + 25 * (forced_deletes + ffi_bridge)`.
- **Max-age timer (`9000.0s` / 2.5 hours)**: forces a background SCIP run once the oldest pending dirty edit reaches 2.5 hours, even if volume stayed below `3500`.
- **Crash-safe persistence**: pending Tier-2 dirty state is atomically persisted to `.arch/scip_pending.json` (`.tmp` + `os.replace`) and cleared only after `_run_scip_reindex` completes, so abrupt process termination never drops un-indexed edits whose `ast_sha256` already updated in Tier-1.

**Reason:** On real multi-language workspaces (e.g., `centrode` Rust + Flutter), `rust-analyzer scip .` takes ~2.5 minutes per run. Triggering SCIP on a 3s debounce wastes CPU on every small edit, while a low volume threshold (`100`) still fires prematurely mid-refactor (a 30-file, 2,000-line AST refactor scores `2450`). Raising the threshold to `3500` with a 2.5h max-age keeps routine editing and medium refactors quiet while bounding worst-case staleness.

**Rejected alternative (pure 3s time-based debounce):** Triggered multi-minute compiler runs after every minor save.

**Rejected alternative (pure volume-count gate without max-age):** Small 1–2 file edits would never trigger background SCIP indefinitely unless followed by unrelated edits.
