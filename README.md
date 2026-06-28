# Arch-mcp

**Arch-mcp** is an Agent-Native Code Intelligence and Compliance Engine. Running as a Model Context Protocol (MCP) server, it empowers AI coding agents to navigate, query, audit, and enforce architectural rules on codebases with compiler-level precision.

It integrates:
*   **SCIP / LSIF** for compiler-level, type-resolved code navigation (definitions and references).
*   **CodeQL** for semantic logic analysis and data-flow path tracing.
*   **Graphify Components** for local ONNX semantic embeddings, context packaging, and incremental change tracking.
*   **Compliance Auditor** to enforce project boundary constraints (layers, tiers, role purity) defined in `config.json`.

---

## Workspace metadata (.arch/)
Inside each indexed project, the engine creates and maintains a local **`.arch/`** folder:
*   **`config.json`**: The architectural rules defining boundaries (e.g., Presentation cannot call Infrastructure).
*   **`arch.db`**: The DuckDB database file containing symbols, relationships, vectors, and audit logs. This is the **single source of truth** for the project.

Both files are ignored in Git (using `.gitignore`).

---

## Project Structure
*   `src/setup/`: Provisioning scripts (`initializer.py`, `downloader.py`, `indexers.py`, `embedder_bootstrap.py`).
*   `src/db/`: Persistence layer connecting DuckDB schema to the project model.
*   `src/engines/`: Wrappers for external tooling (SCIP, CodeQL, ONNX Embedder).
*   `src/agent_instructions/`: Generates custom markdown instructions for LLM agents.
*   `src/interface/`: MCP server and command-line wrappers for agent tools.
*   `src/change_tracker/`: Hashing logic to track code changes and hot-reload indices.
*   `src/reporter/`: Formats code context into token-optimized Markdown report sheets.
*   `src/auditor/`: Evaluates database code nodes against constraints defined in `.arch/config.json`.

---

## Setup & Provisioning

### 1. Initialize Workspace
Creates `.arch/` directory, deploys default `config.json` rule templates, and compiles the local DuckDB tables:
```bash
.venv\Scripts\python src/setup/initializer.py
```

### 2. Setup CodeQL CLI
Downloads, caches (`archive/codeql.zip`), and extracts the CodeQL CLI to the local workspace:
```bash
.venv\Scripts\python src/setup/indexers.py
```
*Note: Running on a script pipeline? Run with `--non-interactive` to bypass prompt questions.*

### 3. Setup ONNX Embedding Model
Prompts the user interactively on console to choose their desired semantic embedding model:
```bash
.venv\Scripts\python src/setup/embedder_bootstrap.py
```
*   **Option 1**: `all-MiniLM-L6-v2` (Default - Light & Fast, ~90MB, 384 dims)
*   **Option 2**: `bge-small-en-v1.5` (High Performance, ~130MB, 384 dims)
*   **Option 3**: `all-mpnet-base-v2` (Maximum Accuracy, ~430MB, 768 dims)

---

## Language Toolchain Prerequisites

### Rust (Cargo)
Rust indexing requires `rust-analyzer` to be installed globally on your machine:
*   *VS Code Notice*: Even if you have the VS Code `rust-analyzer` extension installed, you still need to install the CLI component globally for terminal access. Run:
    ```bash
    rustup component add rust-analyzer
    ```

### Dart / Flutter
Dart indexing requires the `scip_dart` global package. It will be activated automatically during the indexing process if Dart is present on your system path.

