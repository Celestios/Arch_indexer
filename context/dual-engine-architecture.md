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
