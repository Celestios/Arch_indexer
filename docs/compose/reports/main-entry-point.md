---
feature: main-entry-point
status: delivered
specs: []
plans:
  - docs/compose/plans/2026-06-28-main-entry-point.md
branch: master
commits: 30f6c43..e0680d1
---

# Main Entry Point — Final Report

## What Was Built

`src/main.py` serves as the CLI entry point for Arch-mcp, wiring together the initializer, SCIP indexing engine, and compliance auditor into a unified command-line interface. The entry point exposes three subcommands (`init`, `index`, `audit`) that orchestrate the existing modules, plus a bug fix in `repository.py` that was discovered during test authoring.

11 tests were added covering the initializer, auditor, and CLI entry point — all passing.

## Architecture

```
src/main.py
  ├── cmd_init()    → setup.initializer.initialize_workspace
  ├── cmd_index()   → engines.scip_wrapper.ScipWrapper (detect, run, parse, ingest)
  └── cmd_audit()   → auditor.analyzer.Auditor.run_audit
```

**Key files:**
- `src/main.py` — CLI entry point with argparse subcommands
- `src/db/repository.py` — Fixed `add_violation()` CURRENT_TIMESTAMP bug (line 221)
- `tests/test_initializer.py` — 3 tests for workspace setup
- `tests/test_auditor.py` — 4 tests for compliance detection
- `tests/test_main.py` — 4 tests for CLI commands

### Design Decisions

- **Subcommand pattern** over monolithic CLI — each workflow (`init`, `index`, `audit`) is isolated and testable
- **Placeholder interface** — MCP server tools deferred to next iteration; current entry point is functional for local use

## Usage

```bash
# Initialize workspace (creates .arch/, config.json, arch.db)
.venv\Scripts\python src/main.py init .

# Index a project (detects Dart/Rust, runs SCIP, ingests to DB)
.venv\Scripts\python src/main.py index .

# Run compliance audit
.venv\Scripts\python src/main.py audit .
```

## Verification

All 11 tests pass:
```
tests/test_auditor.py::test_auditor_returns_empty_when_no_rules PASSED
tests/test_auditor.py::test_auditor_loads_config PASSED
tests/test_auditor.py::test_auditor_detects_violation PASSED
tests/test_auditor.py::test_auditor_no_false_positives PASSED
tests/test_initializer.py::test_initialize_creates_arch_dir PASSED
tests/test_initializer.py::test_initialize_preserves_existing_config PASSED
tests/test_initializer.py::test_initialize_loads_compliance_rules PASSED
tests/test_main.py::test_main_no_args PASSED
tests/test_main.py::test_cmd_init_creates_workspace PASSED
tests/test_main.py::test_cmd_audit_no_violations PASSED
tests/test_main.py::test_cmd_index_no_languages PASSED
```

## Journey Log

- [bug found] `repository.py:add_violation` had `CURRENT_TIMESTAMP` as a column name instead of a value in the INSERT — fixed by omitting `checked_at` (schema default handles it)
- [lesson] DuckDB doesn't support `CURRENT_TIMESTAMP` in VALUES clause the same way PostgreSQL does — use column defaults instead

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/plans/2026-06-28-main-entry-point.md` | Implementation plan | Complete |
