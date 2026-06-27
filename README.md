# Arch-mcp

**Arch-mcp** is an Agent-Native Code Intelligence and Compliance Engine. It acts as a Model Context Protocol (MCP) server that empowers AI agents to understand, query, debug, and enforce architectural rules on codebases with maximum precision and zero hallucination.

It integrates:
*   **SCIP / LSIF** for compiler-level, type-resolved code navigation (definitions and references).
*   **CodeQL** for semantic logic analysis and data-flow path tracing.
*   **Graphify Components** for local ONNX semantic embeddings, context packaging, and incremental change tracking.
*   **Compliance Auditor** to enforce project boundary constraints (layers, tiers, role purity) defined in `config.json`.

---

## Project Structure

The codebase is organized as follows:
*   `src/setup/`: Handles environment provisioning, binary indexers, and local ONNX models.
*   `src/agent_instructions/`: Generates custom markdown instructions for LLM agents.
*   `src/interface/`: MCP server and command-line wrappers for agent tools.
*   `src/engines/`: Wrappers for external tooling (SCIP, CodeQL, ONNX Embedder).
*   `src/db/`: Persistence layer linking symbols, data flow paths, and compliance violations.
*   `src/change_tracker/`: Hashing logic to track code changes and hot-reload indices.
*   `src/reporter/`: Formats code context into token-optimized Markdown report sheets.
*   `src/auditor/`: Evaluates database code nodes against constraints defined in `config.json`.

---

## Setup & Execution

### 1. Initialization
Runs initializer, indexes the project, downloads models, and configures databases:
```bash
python -m src.main setup
```

### 2. Start MCP Server
Starts the MCP stdin/stdout connection loop:
```bash
python -m src.main mcp
```

### 3. Run Compliance Audit
```bash
python -m src.main audit
```
