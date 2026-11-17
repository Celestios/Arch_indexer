# Arch Interface Reference: CLI & MCP Tools

This guide documents the command-line interface (CLI) and Model Context Protocol (MCP) tools provided by `Arch` for agent-native code intelligence and compliance checking.

---

## 1. CLI Reference

The CLI tool `arch` provides commands for workspace setup, indexing, auditing boundary rules, running reports, and performing manual metadata/compliance configurations.

### Commands

#### `arch init`
*   **Purpose**: The primary interactive CLI entry point. Initializes the workspace, scans source files, downloads the local ONNX embedding models, builds indexing databases, and registers the server automatically with Claude Desktop.
*   **Syntax**:
    ```bash
    arch init [project_root]
    ```
*   **Arguments**:
    *   `project_root` (optional, default: `.`): Path to the target project directory.
*   **Interactive Flow**:
    1.  **Auto-Recognition**: Scans for Rust, Dart, and Python toolchains, reporting availability.
    2.  **Embedder Model prompt**: Prompts the user to choose an ONNX model size:
        *   `[1]` `all-MiniLM-L6-v2` (~90MB download, 384 dimensions)
        *   `[2]` `bge-small-en-v1.5` (~130MB download, 384 dimensions)
        *   `[3]` `all-mpnet-base-v2` (~430MB download, 768 dimensions)
        *   `[4]` Skip model download (disables semantic search)
    3.  **Real-Time Progress Bar**: Downloads the embedder model files, displaying a real-time progress bar.
    4.  **Auto-Indexing**: Automatically executes toolchain indexers and ingests all AST symbols and edge relationships into the DuckDB database.
    5.  **Automated MCP Registration**: Prompts to automatically register the server configuration (virtual environment python interpreter, script arguments, and project paths) inside your Claude Desktop settings (`claude_desktop_config.json`).

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

#### `arch mcp`
*   **Purpose**: Starts and manages the FastMCP server with lifecycle management and single-instance locking.
*   **Syntax**:
    ```bash
    arch mcp [project_root] [--port <port>] [--status] [--stop] [--restart] [--headless]
    ```
*   **Arguments**:
    *   `--port` (optional, default: auto/8071): Custom port for SSE transport.
    *   `--status`: Checks the health and status of the running server (PID, port, URL).
    *   `--stop`: Gracefully terminates the running server instance and clears the lock file.
    *   `--restart`: Stops any existing instance first, then starts a fresh server in the foreground.
    *   `--headless`: Runs the server headlessly as a detached background daemon, displays a clean status notice with PID and URL, and exits. Can be combined with `--restart` (e.g. `arch mcp --restart --headless`).


---

## 2. MCP Tools Reference

The FastMCP server exposes tools returning clean, token-efficient Markdown strings optimized for LLM consumption.

### `lookup`
*   **Purpose**: Resolves symbol and file locations, definitions, occurrences, and direct call relationships. Use this tool like a targeted search or symbol-aware grep to locate a specific node, symbol, function, or class across the codebase when you don't know where it is defined or used.
*   **Parameters**:
    *   `target` (Union[list[str], str], required): Symbol name, file path, or search query.
*   **Output Format (Markdown)**:
    ```markdown
    ## Search Results for: "DbConnection"

    ### Symbol Definitions
    - **db.connection.DbConnection** (Class) in `src/db/connection.py:L9-L75`
    ```

### `context`
*   **Purpose**: Returns structural outlines, declared symbols, class/method signatures, and line ranges for specified files. Use this tool when you know something is located in a specific file but don't know which part, allowing you to inspect its internal structure and locate the exact section or member without reading the entire file.
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
*   **Purpose**: Performs blast radius analysis by computing the transitive closure of upstream callers and downstream callees up to max_depth. Use this tool when evaluating the ripple effects of proposed refactors or deletions, tracing multi-hop failure propagation in defect investigations, assessing coupling between components, or discovering central hub symbols.
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
*   **Purpose**: Compiles a bounded architectural context document by traversing the call graph neighborhood of a focal symbol. Use this tool when assembling targeted multi-hop implementation or refactoring context around a focal point, analyzing vertical execution pipelines across architectural tiers, or conducting forensic defect slicing without manually reading multiple files.
*   **Parameters**:
    *   `symbol` (string, required): Focal symbol name.
    *   `radius` (integer, optional, default: 2): Traversals hops.
    *   `direction` (string, optional, default: 'downstream'): Traversal direction (`downstream`, `upstream`, or `both`).
    *   `resolution` (string, optional, default: 'full'): Resolution profile for neighbors (`full` to include complete source bodies, `signature` to suppress bodies and keep headers/docstrings only).
    *   `out_filepath` (string, optional): Relative path to write the markdown context to.

### `audit`
*   **Purpose**: Runs project-wide architectural boundary and layer compliance checks against configured rules. Use this tool when validating architectural boundaries, verifying that changes do not violate layer or module constraints, checking for circular dependencies, or enforcing structural integrity during code reviews and pre-commit checks.
*   **Parameters**: None
*   **Output Format (Markdown)**:
    ```markdown
    ## Compliance Audit Report: 1 violation(s) found

    1. **[presentation_cannot_directly_call_infrastructure]** (File: `lib/ui/widget.dart:L42`)
       - **Symbol**: `lib.ui.widget.MyWidget.draw`
       - **Violation**: Presentation layer cannot directly call Infrastructure layer
    ```

### `report`
*   **Purpose**: Generates high-level summaries or compliance reports of the workspace code graph. Use this tool when creating executive architectural overviews, summarizing structural metrics and active violations for documentation, or exporting workspace dependency health in Markdown or JSON format.
*   **Parameters**:
    *   `name` (string, required): Name of the report (`overview` or `compliance`).
    *   `format` (string, optional, default: `markdown`): Format of the output (`markdown` or `json`).

### `analyze`
*   **Purpose**: Validates architectural configuration ontology completeness, reachability, and referential sanity. Use this tool when authoring or updating architectural boundary rules, checking configuration syntax and schema integrity, verifying layer and tier definitions, or troubleshooting rule misconfigurations.
*   **Parameters**: None

### `set_fields`
*   **Purpose**: Sets manual architectural metadata fields and tags for a registered file. Use this tool when tagging files with custom architectural metadata, recording module classifications, assigning component responsibilities, or annotating files with inspection notes.
*   **Parameters**:
    *   `filepath` (string, required): Target source file path.
    *   `fields_json` (string, required): JSON string of field-value pairs to set.
    *   `justification` (string, optional): Justification comment explaining the update.

### `clear_pending`
*   **Purpose**: Clears the change-tracker pending audit flags for all files in the database. Use this tool when acknowledging recorded workspace modifications, resetting incremental audit queues after reviewing changes, or resetting change tracker flags.
*   **Parameters**:
    *   `justification` (string, required): Reason for clearing pending audits.

### `set_status`
*   **Purpose**: Sets manual AI logical compliance status for a file (`COMPLIANT` or `VIOLATION_DETECTED`). Flagging a file as `VIOLATION_DETECTED` requires a justification comment and registers a manual logical violation in the compliance catalog. Use this tool when recording architectural review assessments, flagging logical violations or anti-patterns that static rules cannot detect, or approving documented architectural exceptions with justification.
*   **Parameters**:
    *   `filepath` (string, required): Target source file path.
    *   `status` (string, required): Manual compliance status (`COMPLIANT` or `VIOLATION_DETECTED`).
    *   `justification` (string, optional): Justification comment (required for `VIOLATION_DETECTED`).

### `map`
*   **Purpose**: Returns a structured, multi-level architectural blueprint map of the repository, including project totals, structural nodes, key hubs, and directional call flows. Use this tool when exploring an unfamiliar codebase, understanding subsystem boundaries and topologies, discovering inter-module call dependencies, identifying central architectural hubs, or surveying code organization at configurable depths.
*   **Parameters**:
    *   `targets` (list of objects or JSON string, optional): List of query specs to evaluate multiple subtrees simultaneously, e.g. `[{"path": "src", "tree_depth": 1, "detail_level": "folder"}]`.
    *   `path` (string, optional, default: `""`): Starting position in the project tree (`""` for root, or e.g. `"src"`, `"tests"`, `"packages/core"`).
    *   `tree_depth` (integer, optional, default: `1`): How many directory levels deep to group/aggregate (`1` = immediate subfolders, `2` = sub-subfolders, `0` = flat).
    *   `detail_level` (string or integer 1-5, optional, default: `"folder"`): Granularity level: `"folder"` (Level 1/2), `"file"` (Level 3), `"class"` (Level 4), `"symbol"` (Level 5).
    *   `include_external` (boolean, optional, default: `False`): Whether to include standard library and 3rd-party symbols (`builtins`, etc.).
*   **Output Format (Markdown)**:
    ```markdown
    ## Repository Architectural Blueprint Map

    ### Project Totals
    | Files Indexed | Symbols Registered | Dependencies (Call Graph) | Active Violations |
    | :---: | :---: | :---: | :---: |
    | 48 | 1637 | 1789 | 0 |

    ### Architecture Nodes (`src/`, tree_depth=1, detail="folder")
    | Module / Subsystem | Files | Symbols | Inbound | Outbound | Top Hub Symbol (Connections) |
    | :--- | :---: | :---: | :---: | :---: | :--- |
    | `src/db/` | 6 | 520 | 25 | 15 | `db.repository.Repository` (44) |
    | `src/auditor/` | 8 | 316 | 2 | 6 | `auditor.analyzer.Auditor` (94) |

    ### Inter-Module Call Dependencies
    - `src/commands/` ──[8 calls]──> `src/db/`
    - `src/auditor/` ──[6 calls]──> `src/db/`
    ```

### `update`
*   **Purpose**: Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges. Note that the MCP watcher module already auto-updates the database in the background (tree-sitter updates are quick, while SCIP-gathered info might lag). Use this tool only for manual updates when forced synchronization or explicit re-indexing is required.
*   **Parameters**:
    *   `filepaths` (Union[list[str], str], optional): Target file(s) to incrementally update. If omitted, checks all detected languages.
    *   `force` (boolean, optional, default: False): If True, performs a clean full re-index.

