# MCP Tool Semantics & Descriptions

## Skill-style generalized tool descriptions with decoupled lookup and context discovery and watcher-aware update semantics

**Id:** 93cbc631-0e85-4688-b824-91df7e810eb5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer directive, 2026-11-17
**Revisit when:** MCP specification introduces standardized parameter description schemas or tool category registries

All FastMCP tool docstrings in `src/interface/server.py` and `docs/mcp_api.md` follow a standardized "Use this tool when ..." skill-style format using generalized language without embedded concrete examples. The semantic roles of discovery tools are strictly demarcated:
- `lookup` is defined as a symbol-aware grep to find an unknown node/symbol across the codebase.
- `context` is defined for inspecting internal file structure (members, signatures, line ranges) when the target file is known but the relevant section within it is not.
- `update` explicitly clarifies that the background watcher module automatically keeps the DuckDB database current (near-instant for Tree-sitter, potentially lagging for SCIP), reserving manual `update` calls strictly for explicit forced synchronization.
- `map` provides multi-level architectural blueprint summaries without cluttered parameter lists in the prompt description.

**Reason:** Agent models reading MCP tool declarations suffer from cognitive ambiguity when tool docstrings are overly verbose, contain distracting domain-specific examples, or fail to delineate when to use one discovery tool over another. Disambiguating `lookup` (search for a specific node across the repository) versus `context` (navigate an already identified file) prevents agents from executing redundant file reads or un-scoped greps. Explicitly noting that the background watcher automatically updates the database prevents LLMs from wasting tool turns repeatedly calling `update` after standard code edits.

**Rejected alternative:** Including concrete parameter examples directly in docstrings was rejected because examples consume unnecessary context tokens and bias language models toward rigid, pre-canned query shapes. Omitting the watcher note in `update` was rejected because autonomous agents consistently over-indexed files after minor changes despite background watchers running.

## Mandatory project_root parameter across all MCP tools to prevent cross-workspace contamination and silent IDE fallback failures

**Id:** 06d196f3-8932-4d8c-a0e5-396ef5959f7d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer directive, 2026-11-19
**Revisit when:** MCP client specification mandates reverse roots/list capability negotiation across all major agent GUI platforms

All exposed MCP tools (`graph`, `lookup`, `context`, `impact`, `compile_context`, `audit`, `report`, `analyze`, `set_fields`, `clear_pending`, `clear_pending_audits`, `map`, `set_status`, `update`) define `project_root: str` as a mandatory, required parameter in their FastMCP function signature and JSON schema. Synchronous Python test callers and internal CLI callers are adapted via the `_tool()` decorator, which dynamically supplies explicit roots, monkeypatched test server configurations, or filepath ancestry when invoked programmatically without the parameter.

**Reason:** In GUI desktop environments like Google Antigravity, the IDE host runs a single global stdio MCP server process whose working directory is fixed at startup (typically the IDE application install directory or the workspace open during launch). Crucially, GUI desktop agent hosts do not advertise or implement the optional MCP server-to-client reverse RPC `roots/list`. When `project_root` was omitted or made optional, tool calls from secondary open workspaces lacked any workspace context: `ctx.session.list_roots()` silently failed with `MethodNotFound`, causing the resolution logic to fall back to the global process CWD or the persisted `active_project`. Consequently, tools invoked from external repositories (e.g. `centrode`) silently defaulted to and generated artifacts inside the Arch indexer workspace. Making `project_root` strictly mandatory in the schema forces the agent model—which always knows its active workspace path from system prompt metadata—to explicitly pass the target project path on every invocation, eliminating cross-project state pollution.

**Rejected alternative:** Relying solely on `ctx.session.list_roots()` was rejected because desktop MCP client implementations commonly omit reverse root querying capabilities, causing calls to raise exceptions or time out. Relying on optional parameters with CWD/registry fallback was rejected because autonomous agents omit optional parameters whenever possible, silently triggering CWD fallbacks and mutating unintended repositories.

---

## Scoped on-demand SCIP flush only for graph, clusters, and update

**Id:** 65bd99da-97a7-4985-91e2-8247c6ca4990
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session, 2026-11-25
**Revisit when:** Tier-2 SCIP runs are fast enough to flush before high-frequency query tools without noticeable latency

In `src/interface/server.py`, only `graph` and `clusters` call `WatcherManager.get_instance().flush_pending(pctx.root)` before reading DuckDB, and `update` calls `clear_pending()` after syncing so the watcher does not redundantly re-run SCIP. High-frequency tools (`impact`, `context`, `compile_context`, `map`, `audit`, `lookup`, `query`) do **not** flush pending SCIP.

**Reason:** `impact`, `context`, `compile_context`, `map`, and `audit` are invoked frequently during normal agent exploration; flushing SCIP before them would defeat the hybrid Tier-2 gate and trigger repeated multi-minute compiler runs. `graph` and `clusters` are whole-architecture structural commands where fresh cross-file edges are essential and occasional sync latency is acceptable.

**Rejected alternative:** Flushing pending SCIP before every tool that reads `edges` (`impact`, `context`, `compile_context`, `map`, `audit`) — rejected due to excessive re-indexing frequency.

---

## Three-axis compliance model and removal of synthetic pending_audit violations

**Id:** 29112a20-f814-49f6-b3e2-f09bba068314
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session, 2026-11-25
**Revisit when:** compliance storage moves away from DuckDB schema v5

In schema v5 (`src/db/schema.sql`, `src/auditor/analyzer.py`, `src/interface/tools/set_status.py`), compliance state is strictly separated into three orthogonal axes:
1. **Axis 1 (Automatic rules)**: `files.status` (`COMPLIANT` / `VIOLATION_DETECTED`) and `origin = 'automatic'` rows in `compliance_violations`.
2. **Axis 2 (Review queue)**: `files.pending_audit` boolean flag only — `src/auditor/violation_checkers/pending.py` was removed so pending files are never emitted as synthetic violation rows.
3. **Axis 3 (Manual logical review)**: `files.manual_status` defaults to `NULL` (not `'COMPLIANT'`), and `set_status` supports `COMPLIANT`, `VIOLATION_DETECTED`, and `CLEAR` without mutating Axis 1 or triggering `Auditor.run_audit()`.

**Reason:** Modeling `pending_audit` as synthetic violation rows and defaulting `manual_status` to `'COMPLIANT'` caused a freshly initialized repository with zero rule violations to report every file as both violating and manually overridden (e.g., 663/663 violating and 663 manual overrides on `centrode`).

**Rejected alternative:** Filtering `rule_id <> 'pending_audit'` in analytics SQL queries and running `Auditor.run_audit()` inside `set_status` — rejected because it leaked synthetic state across axes and coupled manual review actions to full automatic re-audits.

---

## Moving workspace update from MCP tool to simplified CLI command

**Id:** 87b22379-61d2-47c2-b26c-1b86440293d1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session, 2026-11-25
**See:** mcp-tool-semantics.md#scoped-on-demand-scip-flush-only-for-graph-clusters-and-update — 65bd99da-97a7-4985-91e2-8247c6ca4990 — as of 2026-11-25
**Revisit when:** Tier-2 SCIP indexers become fast enough (sub-second or incremental) to complete reliably within MCP tool-call timeouts

The `update` MCP tool was removed from `src/interface/server.py`, `docs/mcp_api.md`, and the `arch` skill, and replaced by the simplified CLI command `arch update [--force] [project_root]` (`src/commands/update.py`). The `filepaths` and `incremental` flags were omitted from the CLI surface.

**Reason:** `sync_workspace` (`src/engines/sync_pipeline.py`) always executes the full external SCIP indexer (`run_indexer`) in Phase 2 regardless of whether `dirty_files` or `force=False` is passed; `dirty_files` only filters fast Tree-sitter AST sync and post-parse `parse_index` filtering. Running full SCIP indexing inside an MCP tool call regularly exceeds client timeouts, and exposing `filepaths`/`incremental` options suggested partial indexing that could not skip the slow SCIP step.

**Rejected alternative:** Keeping `update` as an MCP tool with `filepaths` / incremental parameters, or restricting `update` to Tree-sitter only — rejected because MCP calls time out on multi-minute SCIP runs, Tree-sitter is already kept current by the background watcher, and `filepaths` did not avoid `run_indexer`.
