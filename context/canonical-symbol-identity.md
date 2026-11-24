# Canonical Symbol Identity & DuckDB Schema v4

## Single source of truth canonical symbol primary keys across Tree-sitter and SCIP

**Id:** 4c1a7e28-1b32-4759-9941-9bf7269d0684
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision and audit review, 2026-11-24
**Revisit when:** Tree-sitter and SCIP engines are unified into a single native compiler library

The symbol identity architecture was overhauled to eliminate fragmented symbol naming, fuzzy line reconcilers, and secondary `clean_symbol` compatibility shims:

1. **Canonical Primary Key Specification (`src/utils/symbol_id.py`)**:
   - Workspace symbols: `<filepath>::<ScopeChain>::<name>` (POSIX normalized relative path).
   - External dependencies: `ext::<manager>/<package>::<ScopeChain>::<name>`.
   - Leaf name (`symbols.name`): Clean identifier only (e.g. `execute`, `UserService`).
   - Raw SCIP descriptor (`symbols.scip_id`): Nullable raw opaque string isolated to SCIP ingress and package blocklists.
   - `symbols.clean_symbol` is completely purged from `schema.sql`, database tables, CSV staging, and all queries.

2. **SCIP Ingress & Parity Fixes (`src/engines/scip/parser.py`, `src/utils/symbol_id.py`)**:
   - **Workspace detection**: Replaced buggy `manager == "."` / `package == "."` check with `resolved_filepath is not None`. Real SCIP indexers (`scip-dart pub <pkg>`, `rust-analyzer cargo <crate>`, `scip-python python <pkg>`) emit full package names; any symbol defined in a workspace document is canonicalized to `<filepath>::...`.
   - **Pass 0 definition pre-indexing**: `parse_index()` performs Pass 0 over all `document.symbols` and definition occurrences across all workspace documents to pre-populate `scip_to_canonical` before resolving references. This prevents cross-file cache poisoning where early external references could freeze symbols as `ext::...`.
   - **Language parity**:
     * *Dart*: Named constructors resolve to `<ClassName>.<named>` (unnamed constructor to `new`); getters and setters normalized with `get:` / `set:` prefixes. Added `extension_declaration` and `mixin_declaration` AST handling.
     * *Rust*: Symmetrical handling of `impl<Trait>` blocks matching `Type<Trait>::method`. Prevented cross-file impls from fabricating nonexistent container IDs.

3. **Inverted Parent Precedence in Semantic Upsert**:
   - In `upsert_semantic_symbols`, parent assignment was flipped to `COALESCE(NULLIF(stg.parent_symbol, ''), symbols.parent_symbol)`.
   - *Reason*: Previously, `COALESCE(symbols.parent_symbol, stg.parent_symbol)` allowed Tier-1's partial or ghost syntactic parent symbol to permanently block Tier-2's type-checked compiler parent symbol from converging in DuckDB.

4. **DuckDB Fail-Fast Schema v4 & Migration Ladder Deletion**:
   - Deleted obsolete v1/v2/v3 ALTER TABLE migration cascades and backfill loops in `connection.py`.
   - The DuckDB index `.arch/arch.db` is strictly a fast, rebuildable cache; on schema version mismatch, `DbConnection` fails fast with an explicit instruction to run `arch init --force`.
   - Dropped the dead `file_co_changes` table in favor of on-the-fly git mining via `git_analyzer.py`.
   - Restored exact `get_symbol(s.symbol = ?)` lookup without ambiguous OR clauses short-circuiting on common leaf names like `init` or `build`.

**Reason:** Eliminating fuzzy `reconciler.py` matching and disparate symbol identifiers ensures Tree-sitter and SCIP converge on identical primary keys. Downstream tools (`lookup`, `context`, `impact`, `compile_context`, `clusters`, `map`) now operate with 100% ID parity across Dart, Rust, and Python without string mangling or demangling heuristics.

**Rejected alternative (Fuzzy line-based reconciler `reconcile_symbol_id`):** Attempting to merge disparate dotted module IDs with raw SCIP strings using a $\pm 2$ line heuristic created false merges between adjacent one-line properties or methods and masked parity defects instead of fixing them at the source.

**Rejected alternative (Preserving `clean_symbol` compatibility column):** Keeping `clean_symbol` led to cascading desynchronization where Tier-1 wrote bare leaf names, Tier-2 wrote dotted module paths, and downstream tools parsed conflicting punctuation (`.`, `::`, `#`).
