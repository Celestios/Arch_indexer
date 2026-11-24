---
name: arch
description: >-
  Architectural intelligence and codebase index. ALWAYS activate and use this skill
  whenever exploring, understanding, navigating, refactoring, modifying, auditing, or analyzing
  the codebase. Only skip if the task does not involve the codebase.
---

# Arch MCP Engine & Codebase Navigation

Arch indexes the codebase into a high-performance symbol and dependency graph.
Whenever you perform any task involving the codebase, you **MUST** prioritize Arch MCP tools over brute-force full-file reads, manual directory scanning, or un-scoped text greps.

Tool-specific schemas and parameter details are provided by the MCP server (`call_mcp_tool`). Use this skill for situational tool selection, execution discipline, architectural enforcement, and initial setup.

---

## 1. Tool Selection by Situation

Select Arch tools based on the abstraction level and lifecycle phase of your task:

| Situation / Objective | Recommended Tool | Purpose |
| :--- | :--- | :--- |
| **High-Level Orientation** | `map` | Architectural overview: symbol communities, module couplings, and key hub symbols. |
| **Emergent Architecture & Drift** | `clusters` | Parameter-free hierarchical clustering, containment scoring, macro subsystems overview, and architectural drift diagnostics. |
| **Locating Code Elements** | `lookup` | Keyword and semantic search across symbols, docstrings, and filenames. |
| **File Outline & Structure** | `context` | Structural Table of Contents (classes, functions, methods, line ranges) without loading full file bodies into memory. |
| **Call Paths & Dependencies** | `graph` | Query caller/callee relationships and dependency links between symbols. |
| **Refactoring & Modifying Code** | `impact` | **Mandatory before edits**: Transitive blast radius analysis (upstream callers / downstream callees) to prevent breakages. |
| **Focused Code Investigation** | `compile_context` | Neighborhood code compilation around a focal symbol (signatures and active bodies across call boundaries). |
| **Architectural Rules & Layers** | `audit` | Check compliance against layer and boundary rules configured for the project. |
| **Violation Deep Dive** | `analyze` | Detailed diagnosis of specific architectural violations or boundary failures. |
| **Metadata & Compliance State** | `set_status`, `set_fields` | Update architectural compliance flags, justification notes, or metadata fields. |
| **Audit Workflow Closure** | `clear_pending` | Clear pending audit flags after reviewing or updating compliant modules. |
| **Audit Timeline & Audit Trail** | `history` | Inspect past audit runs, state transitions, and compliance history. |
| **Index Synchronization** | `update` | Trigger incremental or full re-indexing of modified or newly added files. |
| **Custom Graph / Component Analytics** | `query` | Read-only SQL on DuckDB index (`.arch/arch.db`). **Last resort only**: Do not use frequently; only when no other tool can answer the question. |

---

## 2. Mandatory Enforcement Rules

1. **Arch-First Navigation**:
   - Never search code with broad recursive scans or unscoped filesystem searches when `lookup` or `context` can locate the target symbol or file outline.
   - Never load large source files into context in their entirety. Use `context` to obtain exact line ranges, then inspect only the relevant lines.

2. **Mandatory Blast Radius Check Before Edits**:
   - Before modifying, renaming, or refactoring a function, class, or interface, call `impact` to evaluate all upstream dependents.

3. **Database Staleness & Lag Awareness**:
   - Full SCIP index updates may lag behind recent file edits, though Arch MCP performs fast Tree-sitter updates for immediate symbol/structural changes.
   - When files are modified, created, or deleted during work, call `update` to refresh the index or use alternative methods (such as targeted, bounded line reads).

4. **Query Tool Discipline (Last Resort)**:
   - Do **NOT** use `query` frequently. Always prefer specialized tools (`lookup`, `context`, `graph`, `impact`, `compile_context`, `clusters`, `map`, `audit`).
   - Use `query` only when you have no other better way to retrieve specific graph telemetry or ad-hoc relational joins that no domain tool provides.

---

## 3. Recommended Workflow

```
1. Orient:       map or clusters (overview of subsystems, hubs, and drift) or lookup (known term)
2. Outline:      context (inspect structure and exact line bounds)
3. Safety Check: impact (assess blast radius before touching code)
4. Contextualize: compile_context (gather caller/callee code context if needed)
5. Execute:      Targeted edit on bounded lines
6. Sync & Verify: update (re-index) → audit (verify boundary compliance)
```

---

## 4. Setup & Workspace Initialization

When the user explicitly requests Arch setup:

### Step 1: Pre-Initialization Consultation on `.arch/config.json`
Before running any indexing command, **consult the user** on configuring `.arch/config.json`.
- Refer to [config_guide.md](./references/config_guide.md) for full syntax and schema details:
  - Scopes / path prefixes (`lib/`, `src/`, etc.)
  - Classification fields (`layer`, `role`, `tier`, etc.)
  - Assignment rules & conditions (`path_prefix`, `class_suffix`, `calls_prefix`)
  - Boundary rules (`dependency_check`, `package_restriction`, `naming_convention`)
  - Transitive propagation and barrier definitions
- Help the user draft or review `.arch/config.json`. Configuring top-level directory keys in `config.json` beforehand ensures the indexer immediately recognizes the target source directories without ambiguity.

### Step 2: Validate Configuration Integrity with `analyze`
After drafting or modifying `.arch/config.json`, **always run `analyze`** (via MCP `analyze` tool or terminal `arch analyze`):
- Verifies JSON syntax, schema completeness, and referential integrity.
- Confirms value reachability (ensures all defined classifications are reachable and used).
- If `analyze` reports errors or reachability warnings, resolve them before proceeding to indexing.

### Step 3: Guide the User to Run `arch init` in Terminal
> [!IMPORTANT]
> `arch init` is an **interactive command** that prompts for language selection and directory inclusion via terminal TTY.
> **Do NOT attempt to execute `arch init` autonomously via background or non-interactive subshell tools.** Non-interactive sessions cannot handle interactive TTY prompts.
> 
> **Action**: Instruct the user to run the command in their terminal:
> ```bash
> arch init
> ```
> Inform the user of what prompts to expect:
> 1. Language Indexing Options (confirm detected languages).
> 2. Directory Indexing Options (confirm directories to index).

### Step 4: Post-Initialization Verification
Once the user completes `arch init`:
- Verify `.arch/arch.db` exists.
- Run `map` or `audit` to ensure workspace symbols and compliance rules are active.
