# MCP Lookup Output Design

## Unified references and call graph table with directional flow and target column elimination

**Id:** ad607750-a82a-4635-88cb-87c85424b6b6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** MCP symbol lookup response format is migrated to structured JSON-LD or graphical interactive UI components

The `lookup` MCP tool consolidates syntactic "Symbol Occurrences" and semantic "Call Graph Relationships" into a single, unified `### References & Call Graph` markdown table: `| Location | Symbol / Scope | Relation | Role |`. Redundant repetition of the queried symbol in a dedicated `Target (Callee)` column is eliminated in favor of directional relationship indicators (`←` for incoming callers/implementers, `→` for outgoing callees/dependencies). Multi-relation edges for the same symbol (such as `Implements` and `Calls`) are grouped into a single entry, multi-line references within the same file are collapsed into comma-separated ranges (`L3, L6`), and local symbol names are contextualized without repeating module path prefixes already displayed in the `Location` column.

**Reason:** The previous output separated syntactic references from semantic relationships into two disparate tables, creating massive token bloat and fragmented context. Repeating the queried symbol on every row of the call graph table wasted horizontal width and hundreds of tokens, while callers with multiple relationships generated duplicate rows. Unifying occurrences and call graph relationships into a single cohesive table reduces token overhead by ~70% while improving cognitive clarity for both human developers and LLM agents with zero information loss.

**Rejected alternative:** Keeping two separate tables while merely dropping the `Target` column was rejected because LLM agents had to mentally cross-reference line numbers from the occurrences table with symbols in the call graph table to understand how files and symbols interacted. Fully hierarchical bullet lists were rejected because tabular alignment provides significantly faster visual parsing for multi-file symbol references.
