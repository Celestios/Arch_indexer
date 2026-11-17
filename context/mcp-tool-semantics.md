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
