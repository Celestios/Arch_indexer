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
