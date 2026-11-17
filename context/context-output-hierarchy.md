# Context Tool Output Hierarchy

## Scope-aware tree hierarchy, member nesting, and docstring noise pruning in file context indexing

**Id:** 15170d32-d8ee-4794-8d82-b03133e0ada9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** MCP context output switches to language-server protocol folding ranges or JSON-LD AST representations

The `context` MCP tool categorizes file symbols into a strict structural hierarchy: module-level `### Constants & Variables`, `### Classes` (with methods and fields indented directly under their parent class), and `### Functions` (for top-level functions). Redundant module and class prefixes (`db.connection.DbConnection.`) on members are stripped. Method signatures are inlined directly into item headers (`- def get_connection(...) [L19-33]`), eliminating duplicated method names. Synthetic/fallback SCIP docstrings that merely echo signatures or hover types (such as `builtins.str`, `pathlib.Path`, `def __init__(`, and `(variable)`) are filtered out, displaying docstrings only when authentic human documentation is present.

**Reason:** The previous output dumped all methods, functions, variables, and constants into a flat `### Methods & Functions` list completely detached from the `### Classes` section. Repeating fully-qualified symbol names across every method and field bloated tokens by ~65%, while synthetic SCIP hover strings generated misleading "docstrings" on un-documented symbols. Nesting methods and fields under their respective classes mirrors the actual AST code hierarchy, radically cuts token consumption, and allows LLM agents to instantly parse public class APIs without cross-referencing flat symbol names.

**Rejected alternative:** Flat lists with indentation-based symbol names (e.g. `DbConnection.get_connection`) were rejected because they still required repeating the class prefix across dozens of methods. Dropping docstrings entirely was rejected because genuine class and method summaries provide essential semantic intent to LLM agents during architectural planning.
