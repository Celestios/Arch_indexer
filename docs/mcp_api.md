# Arch Interface Reference: CLI & MCP Tools

This guide documents the command-line interface (CLI) and Model Context Protocol (MCP) tools provided by `Arch` for agent-native code intelligence and compliance checking.

---

## 1. CLI Reference

The CLI tool `arch` is simplified to contain two main commands: one for humans (setup/indexing/integration) and one for automated workflows (compliance checks).

### Commands

#### `arch init`
*   **Purpose**: The primary interactive CLI entry point. Initializes the workspace, scans source files, downloads the local ONNX embedding models, bootstraps the CodeQL CLI binary, builds indexing databases, and registers the server automatically with Claude Desktop.
*   **Syntax**:
    ```bash
    arch init [project_root]
    ```
*   **Arguments**:
    *   `project_root` (optional, default: `.`): Path to the target project directory.
*   **Interactive Flow**:
    1.  **Auto-Recognition**: Scans for Rust and Dart toolchains, reporting availability.
    2.  **Embedder Model prompt**: Prompts the user to choose an ONNX model size:
        *   `[1]` `all-MiniLM-L6-v2` (~90MB download, 384 dimensions)
        *   `[2]` `bge-small-en-v1.5` (~130MB download, 384 dimensions)
        *   `[3]` `all-mpnet-base-v2` (~430MB download, 768 dimensions)
        *   `[4]` Skip model download (disables semantic search)
    3.  **CodeQL CLI prompt**: Prompts the user to download the CodeQL CLI binary (~200MB download). Needed for tracing data flows in compiled code (e.g. Rust).
    4.  **Real-Time Progress Bar**: Downloads the embedder model and CodeQL zip files, displaying a real-time progress bar.
    5.  **Auto-Indexing**: Automatically executes toolchain indexers (Dart/Rust) and ingests all AST symbols and edge relationships into the DuckDB database.
    6.  **CodeQL Database Creation**: If CodeQL CLI is ready and Rust is detected, prompts to build a CodeQL database of the project (`.arch/codeql_db`) to enable tracer queries.
    7.  **Automated MCP Registration**: Prompts to automatically register the server configuration (virtual environment python interpreter, script arguments, and project paths) inside your Claude Desktop settings (`claude_desktop_config.json`).

#### `arch audit`
*   **Purpose**: Runs architectural boundary audits. Ideal for developers to integrate directly into Git pre-commit hooks or CI/CD pipelines to block commits that violate layer boundaries.
*   **Syntax**:
    ```bash
    arch audit [project_root]
    ```
*   **Arguments**:
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch report`
*   **Purpose**: Generates high-level summaries or compliance reports of the workspace code graph.
*   **Syntax**:
    ```bash
    arch report [name] [--format json|markdown] [project_root]
    ```
*   **Arguments**:
    *   `name` (required): The name of the report to run (`overview` or `compliance`).
    *   `--format` (optional, default: `markdown`): Output format format (`markdown` or `json`).
    *   `project_root` (optional, default: `.`): Path to the target project directory.

---

## 2. MCP Tools Reference

The FastMCP server exposes seven tools returning clean, token-efficient Markdown strings optimized for LLM consumption.

### `query`
*   **Purpose**: Semantic similarity search over code docstrings. Supports searching for multiple queries in a single call to minimize roundtrips.
*   **Parameters**:
    *   `text` (Union[list[str], str], required): A single query string or a list of search terms.
    *   `limit` (integer, optional, default: 5): Max search matches per query.
*   **Output Format (Markdown)**:
    ```markdown
    ## Semantic Search Results for: "database connection"

    1. **db.connection.DbConnection** (Similarity: 0.89)
       - **File**: `src/db/connection.py`
       - **Kind**: `Class`
       - **Signature**: `class DbConnection`
       - **Doc**: Manages connection lifecycle to DuckDB database...

    ## Semantic Search Results for: "boundary check"

    1. **auditor.analyzer.Auditor.run_audit** (Similarity: 0.82)
       - **File**: `src/auditor/analyzer.py`
       - **Kind**: `Method`
       - **Signature**: `def run_audit(self, filepath_filter: Optional[str] = None)`
    ```

### `context`
*   **Purpose**: Lightweight file Table of Contents (TOC) with line ranges, letting agents target narrow, line-range reads using their file viewer.
*   **Parameters**:
    *   `filepath` (string, required): Path to the file.
*   **Output Format (Markdown)**:
    ```markdown
    ## File Index: `src/db/repository.py`

    ### Classes
    - **db.repository.Repository** [L5-395] (class)
      * Data Access Object (DAO) for the Arch-mcp DuckDB database...

    ### Methods & Functions
    - **db.repository.Repository.get_symbol** [L101-118]
      * *Signature*: `def get_symbol(self, symbol: str) -> Optional[Dict]`
      * *Docstring*: Retrieves details of a registered symbol declaration.
    ```

### `impact`
*   **Purpose**: Blast-radius computation. Traces call chains upstream (callers) and downstream (callees) transitively.
*   **Parameters**:
    *   `symbol` (string, required): Fully qualified symbol name.
    *   `max_depth` (integer, optional, default: 3): BFS traversal depth limit.
*   **Output Format (Markdown)**:
    ```markdown
    ## Blast Radius for: `db.repository.Repository.get_symbol`

    ### ── Upstream Callers (Who calls this?)
    - **src.interface.server.arch_context** [Depth: 1]
      * Path: `src.interface.server.arch_context` ──> `Repository.get_symbol`

    ### ── Downstream Callees (What does this call?)
    - **db.connection.DbConnection.session** [Depth: 1]
      * Path: `Repository.get_symbol` ──> `DbConnection.session`
    ```

### `audit`
*   **Purpose**: Runs the boundary audit. Can be restricted to a specific subtree.
*   **Parameters**:
    *   `filepath` (string, optional): Restricts evaluation to code calling from matching file path prefixes.
*   **Output Format (Markdown)**:
    ```markdown
    ## Compliance Audit: 1 violation(s) found

    1. **[presentation_cannot_directly_call_infrastructure]** (File: `lib/ui/widget.dart:L42`)
       - **Caller Symbol**: `lib.ui.widget.MyWidget.draw`
       - **Violation**: Presentation layer cannot directly call Infrastructure layer
    ```

### `map`
*   **Purpose**: Provides a bird's-eye modular map of code structure using Label Propagation (LPA) community detection, listing key hub entry points and inter-module dependencies.
*   **Parameters**: None
*   **Output Format (Markdown)**:
    ```markdown
    ## Repository Architectural Blueprint Map

    ### Project Totals
    - **Files Indexed**: 45
    - **Symbols Registered**: 412
    - **Dependencies (Call Graph Edges)**: 1,289
    - **Active Architectural Violations**: 1

    ### Detected Architectural Communities
    #### Community: `lib/ui/` (85 symbol(s))
      - **Key Hub Symbols**:
        * `lib.ui.widget.MyWidget.draw` (Connections: 24)
        * `lib.ui.theme.DarkTheme` (Connections: 12)

    #### Community: `src/db/` (45 symbol(s))
      - **Key Hub Symbols**:
        * `db.repository.Repository` (Connections: 45)
        * `db.connection.DbConnection` (Connections: 15)

    ### Inter-Community Call Dependencies
    - `lib/ui/` ──[12 call(s)]──> `src/db/`
    ```

### `trace`
*   **Purpose**: Uses CodeQL to trace a data flow path from a source symbol to a sink symbol.
*   **Parameters**:
    *   `source` (string, required): Source symbol name.
    *   `sink` (string, required): Sink/destination symbol name.
*   **Output Format (Markdown)**:
    ```markdown
    ## Data Flow Trace: Path Found (2 steps)

    1. `src.web.handler.UserHandler.post` (`src/web/handler.py:L23`)
    2. `db.repository.Repository.upsert_symbol` (`src/db/repository.py:L71`)
    ```

### `report`
*   **Purpose**: Generates a structured overview or compliance violation report of the workspace.
*   **Parameters**:
    *   `name` (string, required): Name of the report (`overview` or `compliance`).
    *   `format` (string, optional, default: `markdown`): Format of the output (`markdown` or `json`).
*   **Output Format (Markdown)**:
    ```markdown
    # Workspace Overview Report

    ## Repository Totals
    - **Files Indexed**: 12
    - **Symbols Registered**: 154
    - **Dependencies (Call Graph Edges)**: 450
    - **Active Architectural Violations**: 0
    ```
