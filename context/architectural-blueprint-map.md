# Architectural Blueprint Map

## Dynamic, modular multi-target querying with decoupled tree depth and detail level

**Id:** ccbb045f-8b6f-41fe-b511-5e7333c0766c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** repository navigation switches to an external graph query language (such as Cypher or GraphQL)

The MCP `map` tool accepts modular target queries (`targets: List[Dict[str, Any]]`) or single-target kwargs, parameterized by starting position (`path`), tree expansion depth (`tree_depth`), entity resolution granularity (`detail_level`: `"folder"`, `"file"`, `"class"`, `"symbol"`), and an external dependency toggle (`include_external`). Multiple targets can be evaluated in a single round-trip.

**Reason:** Real-world repositories vary widely in structure (Go `cmd`/`pkg`, Java `src/main`, Monorepos with `packages/*`, colocated test suites). Hardcoded assumptions (such as rigid `src` vs. `tests` toggles) break generic usability across diverse tech stacks. Decoupling folder tree traversal depth from structural entity granularity allows AI agents to inspect macro subsystems or zoom directly into localized files/classes in one request without context window dilution.

**Rejected alternative:** A binary `scope="src" | "full"` parameter was rejected because it imposed hardcoded project layout assumptions and could not accommodate monorepos, multi-package layouts, or localized deep-dives. Conflating folder depth and code entity resolution into a single integer level was also rejected because it prevented inspecting deep subpackages at a macro level or root files at class-level granularity.

## Excluding external symbols from default architectural blueprint and hub calculations

**Id:** 2e345125-60b8-423b-ad12-f169bb667e04
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** 3rd-party library dependency auditing is added as an independent analyzer engine

Symbols with `filepath IS NULL` (language builtins such as `builtins.str`, `typing`, and 3rd-party imports) are excluded from the default architectural map (`include_external=False`). They are only processed when explicitly requested via `include_external=True` or `path="external"`.

**Reason:** In large codebases, language primitives and utility types dominate symbol counts and call edge degrees, artificially creating misleading "top hub" designations (e.g., `builtins.str` having 82 connections) and overwhelming the actual domain architecture with hundreds of external symbols. Excluding them by default isolates true internal domain dependencies.

**Rejected alternative:** Treating `external/` as a primary architectural community alongside domain code was rejected because it polluted internal call graphs and distorted structural coupling metrics.

## Table-first presentation with retained directional call dependency arrows

**Id:** e739e4d3-bf03-4a68-9422-3d575cec5f3a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** interactive canvas widgets or SVG diagrams replace markdown tool outputs in client interfaces

The blueprint map output replaces repetitive bulleted "community" lists with concise Markdown tables for totals and target nodes, while retaining explicit directional dependency arrows (`Source ──[N calls]──> Target`) sorted by call volume and filtering out 0-connection symbols.

**Reason:** Verbose bulleted lists with repeated headers created ~70% token overhead and impaired legibility for LLM agents. Markdown tables provide compact, dense structural overviews, while explicit arrow notation retains clear directional dependency flow between components.

**Rejected alternative:** Replacing directional arrows with a matrix or speculative synthetic "flow descriptions" was rejected because artificial descriptions lack ground truth in the database, and arrow notation provides the most unambiguous visual representation of call graph directionality.
