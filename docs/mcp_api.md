# Arch Interface Reference: CLI & MCP Tools

This guide documents the command-line interface (CLI) and Model Context Protocol (MCP) tools provided by `Arch` for agent-native code intelligence and compliance checking.

---

## 1. CLI Reference

The CLI tool `arch` provides commands for workspace setup, indexing, auditing boundary rules, running reports, and performing manual metadata/compliance configurations.

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
    arch report <name> [--format markdown|json] [project_root]
    ```
*   **Arguments**:
    *   `name` (required, choices: `overview`, `compliance`): The name of the report to run.
    *   `--format` (optional, default: `markdown`): Output format (`markdown` or `json`).
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch set-status`
*   **Purpose**: Manually overrides or sets the logical compliance status flag of a file.
*   **Syntax**:
    ```bash
    arch set-status <filepath> <status> [justification] [project_root]
    ```
*   **Arguments**:
    *   `filepath` (required): Filepath to the target file.
    *   `status` (required, choices: `COMPLIANT`, `VIOLATION_DETECTED`): Manual logical compliance status.
    *   `justification` (optional): Explanation/reasoning comment (required if status is `VIOLATION_DETECTED`).
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch set-fields`
*   **Purpose**: Sets manual metadata fields for a file.
*   **Syntax**:
    ```bash
    arch set-fields <filepath> <fields_json> [justification] [project_root]
    ```
*   **Arguments**:
    *   `filepath` (required): Filepath to the target file.
    *   `fields_json` (required): JSON-formatted string of field-value pairs to update.
    *   `justification` (optional): Optional justification comment for the update.
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch clear-pending`
*   **Purpose**: Clears the pending audit flag on all files in the database.
*   **Syntax**:
    ```bash
    arch clear-pending <justification> [project_root]
    ```
*   **Arguments**:
    *   `justification` (required): Justification comment explaining why the pending audits are being cleared.
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch watch`
*   **Purpose**: Watches the project root for file changes, triggering automatic re-indexing and compliance auditing when edits are detected.
*   **Syntax**:
    ```bash
    arch watch [--debounce <seconds>] [project_root]
    ```
*   **Arguments**:
    *   `--debounce` (optional, default: `3.0`): Debounce delay in seconds before performing index/audit.
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch analyze`
*   **Purpose**: Validates the architectural configuration ontology (`config.json`) completeness and sanity. Checks syntax, structure, allowed values reachability, and dependency rules referential integrity.
*   **Syntax**:
    ```bash
    arch analyze [project_root]
    ```
*   **Arguments**:
    *   `project_root` (optional, default: `.`): Path to the target project directory.

#### `arch impact`
*   **Purpose**: Performs blast radius / transitive dependency analysis for a symbol by computing its transitive callers and callees.
*   **Syntax**:
    ```bash
    arch impact <symbol> [--max-depth <depth>] [project_root]
    ```
*   **Arguments**:
    *   `symbol` (required): Fully qualified target symbol name.
    *   `--max-depth` (optional, default: `3`): Maximum depth of call chain traversal.
    *   `project_root` (optional, default: `.`): Path to the target project directory.

---

## 2. MCP Tools Reference

The FastMCP server exposes tools returning clean, token-efficient Markdown strings optimized for LLM consumption.

### `lookup`
*   **Purpose**: Resolves symbol and file locations, definitions, occurrences, and direct call relationships.
*   **Parameters**:
    *   `target` (Union[list[str], str], required): Symbol name, file path, or search query.
*   **Output Format (Markdown)**:
    ```markdown
    ## Search Results for: "DbConnection"

    ### Symbol Definitions
    - **db.connection.DbConnection** (Class) in `src/db/connection.py:L9-L75`
    ```

### `context`
*   **Purpose**: Lightweight file Table of Contents (TOC) with line ranges, letting agents target narrow, line-range reads using their file viewer. Accepts multiple files.
*   **Parameters**:
    *   `filepaths` (Union[list[str], str], required): A single filepath, a comma-separated string, or a list of file paths.
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
    *   `max_depth` (integer, optional, default: 3): Traversal depth limit.
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

### `compile_context`
*   **Purpose**: BFS-traverses the call graph neighborhood of a focal symbol, dynamically extracting raw source code blocks directly from the filesystem using line coordinates, and returns a unified markdown context report.
*   **Parameters**:
    *   `symbol` (string, required): Focal symbol name.
    *   `radius` (integer, optional, default: 2): Traversals hops.
    *   `direction` (string, optional, default: 'downstream'): Traversal direction (`downstream`, `upstream`, or `both`).
    *   `resolution` (string, optional, default: 'full'): Resolution profile for neighbors (`full` to include complete source bodies, `signature` to suppress bodies and keep headers/docstrings only).
    *   `out_filepath` (string, optional): Relative path to write the markdown context to.

### `audit`
*   **Purpose**: Runs the project-wide boundary audit check.
*   **Parameters**: None
*   **Output Format (Markdown)**:
    ```markdown
    ## Compliance Audit Report: 1 violation(s) found

    1. **[presentation_cannot_directly_call_infrastructure]** (File: `lib/ui/widget.dart:L42`)
       - **Symbol**: `lib.ui.widget.MyWidget.draw`
       - **Violation**: Presentation layer cannot directly call Infrastructure layer
    ```

### `report`
*   **Purpose**: Generates a structured overview or compliance violation report of the workspace.
*   **Parameters**:
    *   `name` (string, required): Name of the report (`overview` or `compliance`).
    *   `format` (string, optional, default: `markdown`): Format of the output (`markdown` or `json`).

### `analyze`
*   **Purpose**: Validates the architectural configuration ontology (`config.json`) completeness and sanity. Checks syntax, structure, allowed values reachability, and dependency rules referential integrity.
*   **Parameters**: None

### `set_fields`
*   **Purpose**: Updates manual compliance status or metadata fields for files, strictly validating them against the project ontology (`config.json`).
*   **Parameters**:
    *   `filepath` (string, required): Target source file path.
    *   `fields_json` (string, required): JSON string of field-value pairs to set.
    *   `justification` (string, optional): Justification comment explaining the update.

### `clear_pending`
*   **Purpose**: Clears the change-tracker pending audit flags for all files in the database.
*   **Parameters**:
    *   `justification` (string, required): Reason for clearing pending audits.
