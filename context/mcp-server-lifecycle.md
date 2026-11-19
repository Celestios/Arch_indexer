# MCP Server Lifecycle Management

## Foreground execution by default with informative conflict notice and explicit lifecycle management flags

**Id:** 6376ffe4-44a1-42ca-b5d0-f322201d7e06
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** server lifecycle transitions to a system service manager (systemd / Windows Service) or container runtime

The `arch mcp` CLI command runs the FastMCP server in the foreground of the invoking terminal by default. Startup displays an informative banner with the active listening port, URL, process PID, transport protocol, and registered tools. When a server instance is already running on the project, the CLI does not silently output a bare URL and exit; instead, it reports a diagnostic summary detailing the running instance (PID, URL, health) and provides actionable commands (`--stop`, `--restart`, `--status`). Explicit lifecycle flags (`--stop`, `--restart`, `--status`) allow controlling the instance without manual process killing.

**Reason:** Running in the foreground enables real-time stream logging and clean termination using standard `Ctrl+C`. Previously, the single-instance locking check simply printed the server URL and immediately called `sys.exit(0)`, leading developers to believe the CLI had launched a background daemon. In reality, it was silently exiting against an orphaned background instance, leaving developers unable to view logs, unable to terminate the process via `Ctrl+C`, and unable to restart the server without manual task killing.

**Rejected alternative:** Automatically killing the existing server on every invocation was rejected because another active agent, IDE plugin, or terminal tab might be actively issuing requests. Raw silent URL-and-exit was rejected because it stripped away developer visibility and created zombie background processes.

## Detached headless daemon execution via optional --headless modifier with health handshake

**Id:** 220c3ae4-fdb9-47bd-9fea-95176aba8ff5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-17
**Revisit when:** MCP client connectivity shifts from local SSE/stdio daemons to remote hosted endpoints

The `arch mcp` and `arch mcp --restart` commands accept an optional `--headless` modifier. In headless mode, the server is spawned as a detached background daemon (`DETACHED_PROCESS` and `CREATE_NO_WINDOW` on Windows; new session on Unix) with stdout and stderr redirected to `.arch/mcp.log`. The parent process performs a verified HTTP health check handshake (up to 5 seconds) before printing a clean confirmation notice with the URL, PID, and log path, then exits back to the shell prompt without shutting down the server.

**Reason:** Automated workflow scripts, CI runners, and background orchestrators need to spin up the MCP server without blocking the terminal session or script runner. Decoupling this capability into an explicit `--headless` modifier preserves foreground live logging as the developer default while granting full background daemonization on demand. Performing a startup health check before exiting ensures failures (such as port collisions or missing databases) are immediately caught and reported rather than exiting silently with a dead process.

**Rejected alternative:** Relying on shell-level backgrounding (`Start-Job` / `&`) was rejected because process group boundaries, console handle inheritance, and job object lifecycles vary across OS environments and frequently kill child servers upon parent shell exit. Exiting immediately without the HTTP health verification handshake was rejected because any initialization error would leave the user assuming the server was operational.

## Non-mutating stdio server startup preventing active_project clobbering in multi-project registry

**Id:** 62bc09e4-5598-4025-9c9a-32c7f349c746
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-19
**Revisit when:** MCP daemon transitions to per-window isolated ephemeral transport instances

Starting the FastMCP server in stdio mode (`run_server()` in `src/interface/server.py` and `arch mcp --stdio` in `src/commands/mcp.py`) does not automatically register the server's launch directory into `~/.arch/projects.json` and does not overwrite `active_project`. Project contexts and database connections are instantiated lazily on demand when tools are invoked with a specific `project_root`. Furthermore, `ProjectRegistry.register_project` only initializes the `active_project` pointer if no valid active project is currently set, or if explicitly requested.

**Reason:** When IDEs (such as Antigravity) launch global MCP background processes, the process is spawned with whatever working directory was active when the editor initialized or from the application binary directory. Previously, `run_server()` called `registry.register_project(default_root)` unconditionally upon boot. If `arch.db` existed in the launching directory (e.g. `Arch_indexer`), this boot sequence silently overwrote `active_project` in `~/.arch/projects.json` to `Arch_indexer`, hijacking tool calls from any other opened projects. By decoupling server process boot from workspace activation, the registry preserves user-selected active projects across editor restarts.

**Rejected alternative:** Overwriting `active_project` on every server boot was rejected because global background servers serve multiple projects concurrently and must not mutate persistent user preferences based solely on where the host process binary happened to be spawned.
