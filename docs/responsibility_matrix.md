# Component & Engine Responsibility Matrix

## 1. Engines: AST Engine (Tree-sitter) vs. Semantic Engine (SCIP)

| Capability / Task | Responsible Engine | Scope | Resolution Level | Latency Characteristic |
| :--- | :--- | :--- | :--- | :--- |
| **Live Line-Range & Offset Sync** | Tree-sitter | File-local | Syntactic declaration boundaries | Sub-2ms on file save |
| **Exact Enclosing Scope Resolution** | Tree-sitter | File-local | Parent class/function body span | Sub-millisecond |
| **Multi-Line Signature & Docstring Extraction** | Tree-sitter | File-local | Exact AST syntax nodes | Sub-millisecond |
| **Decorator, Attribute & Visibility Tagging** | Tree-sitter | File-local | AST declaration metadata (`@mcp.tool`, `#[no_mangle]`, `extern "C"`, `pub`) | Sub-millisecond |
| **Control-Flow Call Site Context** | Tree-sitter | Function-local | Call-enclosing structure (`[in loop]`, `[in try/catch]`, `[conditional]`) | Sub-millisecond |
| **Skeleton Code Folding** | Tree-sitter | File-local | Statement block suppression with signature preservation | Sub-millisecond |
| **Complexity & Nesting Metrics** | Tree-sitter | Function-local | Cyclomatic complexity, max nesting depth, cognitive load | Sub-millisecond |
| **Syntax Anti-Pattern & Structural Rules** | Tree-sitter | File-local | S-expression pattern matching (`.unwrap()`, bare `except:`, raw SQL) | Sub-millisecond |
| **Zero-Toolchain & Broken Code Fallback** | Tree-sitter | File-local | Error-tolerant syntax parsing when compilation fails | Sub-millisecond |
| **Cross-File Call Graph Resolution** | SCIP | Workspace / Cross-package | Exact caller-to-callee symbol edges across imports and aliases | Compiler pass (seconds) |
| **Trait, Interface & Implementation Mapping** | SCIP | Workspace / Cross-crate | `is_implementation` relationships connecting traits to concrete types | Compiler pass (seconds) |
| **Inferred Type & Generic Resolution** | SCIP | Workspace | Concrete resolved types for chained calls and generic instantiations | Compiler pass (seconds) |
| **Read vs. Write State Mutation Tracking** | SCIP | Workspace | `SymbolRole` bitmasks (`ReadAccess` 0x8 vs. `WriteAccess` 0x4) | Compiler pass (seconds) |
| **Transitive Call Closure & Blast Radius** | SCIP + Database | Workspace | Multi-hop upstream callers and downstream callees | Single-join SQL queries |
| **External & Third-Party Dependency Tracking** | SCIP | Workspace / Package registry | Standard library and external package symbols (`external_symbols`) | Compiler pass (seconds) |
| **Compiler Diagnostic & Deprecation Extraction** | SCIP | Workspace | Diagnostics (`Severity`, compiler error codes, deprecation tags) | Compiler pass (seconds) |
| **Test-to-Production Coverage Linking** | SCIP + Database | Workspace | `SymbolRole.Test (0x20)` reverse linking to production targets | Database join |

---

## 2. Change Tracker (`src/change_tracker/`)

| Component | Responsibility | Inputs | Outputs |
| :--- | :--- | :--- | :--- |
| **Watcher (`watcher.py`)** | Detects filesystem events, resolves sub-package roots, coordinates immediate Tree-sitter sync and throttled SCIP batch runs | Filesystem save/delete events | Triggered ingestion tasks, scoped file batches |
| **Invalidation Engine (`invalidation.py`)** | Computes minimal dirty file set using single-hop SQL join and old vs. new symbol signature diffing | Modified file paths, existing DB symbols | Expanded invalidated file set |
| **Content Tracker (`tracker.py`)** | Computes SHA-256 hashes of source files and architectural config | File and config paths | SHA-256 digests, configuration change flags |
| **Git Coupling Miner (`git_coupling.py`)** | Mines commit history from `git log` to extract pairwise co-change counts and coupling frequencies | Git repository commit log | Pairwise file co-change records in `file_co_changes` |

---

## 3. Auditor (`src/auditor/`)

| Component | Responsibility | Inputs | Outputs |
| :--- | :--- | :--- | :--- |
| **Analyzer (`analyzer.py`)** | Coordinates workspace-wide compliance checks, triggers symbol classification, and updates file statuses | AST + SCIP symbols, edges, `.arch/config.json` | Compliance violation records, file compliance statuses |
| **Classifier (`classifier.py`)** | Evaluates static assignment rules and manual field mappings per symbol | Symbol metadata, file paths, config rules | Computed symbol architectural fields (`layer`, `tier`, etc.) |
| **Metadata Propagator (`propagation.py`)** | Propagates classifications upstream or downstream along call graph edges until barrier fields | Classifications, call edges, propagation rules | Transitive symbol classifications, propagation traces |
| **Path Tracer (`path_tracer.py`)** | Reconstructs physical call paths between violating source and target symbols | Call graph edges, propagation traces | Formatted human-readable violation call traces |
| **Config Loader (`config_loader.py`)** | Loads, normalizes, and matches `.arch/config.json` rules by longest matching path prefix | `.arch/config.json` | Scoped prefix configuration objects |
| **Field Validator (`field_validator.py`)** | Validates schema conformance of manual fields and resets invalid values | Symbol/file manual fields, config schemas | Sanitized manual field records |
| **Edge Weight Updater (`edge_weights.py`)** | Calculates coupling weights between connected symbols based on architectural boundaries | Connected symbol layers, barrier definitions | Normalized edge weights in DuckDB |
| **Violation Checkers (`violation_checkers/`)** | Enforces layer dependency rules, naming conventions, package restrictions, and barrier intermediaries | Symbol classifications, call edges, compliance rules | Formatted compliance violation entries with fix hints |
| **Context Compiler (`compiler.py`)** | Compiles token-budgeted markdown context using weighted Dijkstra traversal, type resolution, and degradation | Focal symbol, radius, direction, resolution, token budget | Structured markdown context document |

---

## 4. Database Layer (`src/db/`)

| Component | Responsibility | Storage Target | Key Operations |
| :--- | :--- | :--- | :--- |
| **Connection Manager (`connection.py`)** | Manages DuckDB connection pool, transaction contexts, and automatic schema migrations | DuckDB file (`.arch/arch.db`) | Schema initialization, session yielding, safe column migrations |
| **Symbols Repository (`repository_symbols.py`)** | CRUD operations for symbol declarations, AST parent references, diagnostics, and churn counts | `symbols`, `occurrences`, `diagnostics` | Bulk symbol upserts, occurrence coordinates, keyword/exact lookups |
| **Edges Repository (`repository_edges.py`)** | Storage and graph traversal queries for structural relationships | `edges` | Weighted edge insertion, incoming/outgoing queries, transitive closures |
| **Files Repository (`repository_files.py`)** | Tracks workspace source files, indexing timestamps, hashes, and compliance statuses | `files` | Bulk file upserts, status updates, pending audit tracking |
| **Compliance Repository (`repository_compliance.py`)** | Manages architectural rules and recorded violations | `compliance_rules`, `compliance_violations` | Rule registration, violation upserts, file-scoped violation deletions |
| **Cascade Service (`cascade.py`)** | Coordinates cross-table cascading deletes when files are modified or removed | All database tables | Bulk deletion of edges, occurrences, diagnostics, and symbols |

---

## 5. Interface & Commands Layer (`src/interface/`, `src/commands/`)

| Component | Responsibility | Inputs | Outputs |
| :--- | :--- | :--- | :--- |
| **MCP Server (`server.py`)** | Exposes MCP tools (`lookup`, `context`, `impact`, `compile_context`, `audit`) over stdio | MCP protocol requests | JSON-RPC tool responses |
| **Formatters (`formatters.py`)** | Formats database graph entities into agent-readable markdown tables, badges, and code blocks | Database tuples, occurrences, edges | Formatted markdown text |
| **Impact Tool (`impact.py`)** | Computes blast radius, partitions callers into production, tests, and entry points, and flags churn | Symbol identifier, max depth | Blast radius report with test coverage and entry points |
| **Lookup Tool (`lookup.py`)** | Resolves single symbols or files with signatures, occurrences, diagnostics, and test coverage | Target symbol name or file path | Detailed symbol/file markdown index |
| **Context Tool (`context.py`)** | Generates structural index of requested files with line ranges, signatures, and inline badges | List of file paths | Multi-file structural summary markdown |
| **CLI Commands (`commands/`)** | Implements terminal CLI entry points (`arch init`, `arch audit`, `arch watch`, `arch impact`) | CLI arguments and flags | Exit codes, terminal status reports |
