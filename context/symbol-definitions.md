# Symbol Definitions

## Persisting defining code blocks in the DuckDB symbols table

**Id:** 8b32cd91-8d70-4b0c-8535-9a26104ac8f9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-16
**Revisit when:** code intelligence switches to out-of-process LSP document symbol providers with remote body fetching

Defining code blocks for methods, functions, constructors, and classes are extracted during the initial indexing pass (via `CodeExtractor` AST traversal and syntactic fallback) and stored directly in DuckDB's `symbols` table under the `code_block TEXT` column, alongside signature, docstring, and body hash metadata.

**Reason:** Persisting definition bodies in the database provides a centralized source of truth across all tools (MCP context servers, graph builders, and auditing engines). Decoupling code retrieval from filesystem reads allows offline inspection, eliminates redundant AST parsing during visualization builds, and avoids inconsistencies if workspace files are modified or deleted after indexing.

**Rejected alternative:** On-the-fly AST extraction during graph HTML generation was initially tested but rejected per maintainer instruction. It tightly coupled the graph builder to disk access, duplicated parsing work across repeated builds, and left downstream tools unable to inspect symbol implementations from the database.

## Dedicated contextual code viewer modal with top-right toggle button

**Id:** 9d1ad854-2457-4bf5-b28e-1cdadc302d6d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer UI design specification, 2026-11-16
**Revisit when:** the visualizer replaces canvas inspection with a dockable IDE side-panel system

In the circuit board visualizer, defining code blocks are accessed through a contextual top-right button (`#btn-view-code`) that dynamically appears when an object (class, method, or function) is selected on the canvas or via search. Clicking the button opens a centered, high-contrast modal (`#code-viewer-modal`) featuring an IDE-style line number gutter (`#code-gutter`), source file coordinates, a clipboard copy action, and multiple dismissal triggers (Escape, modal close button, backdrop click).

**Reason:** Methods and classes frequently span 30 to 100+ lines. Cramming multi-line code blocks into the fixed-width 360px inspector pane caused excessive vertical expansion and awkward horizontal scrolling. A dedicated modal preserves code formatting and readability with synchronized line numbers while keeping the top-right button unobtrusive when no component is selected.

**Rejected alternative:** Embedding the full code snippet directly inside the inspector sidebar was rejected because it overwhelmed the inspector's terminal port mappings and trace lists, degrading navigation for high-fanout chips.
