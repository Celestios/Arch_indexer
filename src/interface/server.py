import os
import sys
import json
import asyncio
import functools
import contextvars
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional, List, Union, Dict, Any

# Setup sys.path to resolve imports from src/
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import FastMCP, Context
from db.repository import Repository
from interface.project_registry import ProjectRegistry, find_project_root_with_db
from change_tracker.watcher_manager import WatcherManager
from interface.server_config import get_project_root as get_default_project_root
from interface.tools.context import handle_context
from interface.tools.lookup import handle_lookup
from interface.tools.impact import handle_impact
from interface.tools.audit import handle_audit
from interface.tools.compile_context import handle_compile_context
from interface.tools.map import handle_map
from interface.tools.update import handle_update
from interface.tools.set_status import handle_set_status
from interface.tools.graph import handle_graph
from interface.validators import validate_direction, validate_resolution

mcp = FastMCP("arch")
_explicit_project_root = contextvars.ContextVar("_explicit_project_root", default=None)


def uri_to_path(uri: str) -> Path:
    """Converts a file:// URI or local path string to a resolved Path."""
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        host = parsed.netloc or ""
        path = urllib.request.url2pathname(parsed.path)
        if host:
            path = f"\\\\{host}{path}"
        return Path(path).resolve()
    return Path(uri).resolve()


def _tool():
    """Registers an async tool with FastMCP while enabling synchronous execution in test suites."""
    def decorator(fn):
        mcp.tool()(fn)

        @functools.wraps(fn)
        def caller(*args, project_root: Optional[Union[str, Path]] = None, **kwargs):
            if project_root is not None:
                kwargs["project_root"] = str(project_root)
            token = _explicit_project_root.set(str(project_root) if project_root else None)
            try:
                import inspect
                sig = inspect.signature(fn)
                if "project_root" in sig.parameters and "project_root" not in kwargs:
                    param_names = list(sig.parameters.keys())
                    root_idx = param_names.index("project_root")
                    if len(args) <= root_idx:
                        # Fallback for Python/test callers: resolve from contextvar, filepath ancestry, server_config, or registry
                        fallback = _explicit_project_root.get()
                        if not fallback:
                            fp = kwargs.get("filepath") or kwargs.get("filepaths") or kwargs.get("path")
                            if not fp and len(args) > 0:
                                cand = args[0]
                                if isinstance(cand, list) and cand:
                                    cand = cand[0]
                                if isinstance(cand, (str, Path)) and Path(cand).is_absolute():
                                    fp = cand
                            if fp and isinstance(fp, (str, Path)) and Path(fp).is_absolute():
                                db_root = find_project_root_with_db(fp)
                                if db_root is not None:
                                    fallback = str(db_root)

                        if not fallback:
                            server_cfg = sys.modules.get("interface.server_config")
                            if server_cfg and hasattr(server_cfg, "_resolved") and "project_root" in server_cfg._resolved:
                                fallback = str(server_cfg._resolved["project_root"])

                        if not fallback:
                            if "ARCH_PROJECT_ROOT" in os.environ:
                                fallback = os.environ["ARCH_PROJECT_ROOT"]
                            else:
                                reg = ProjectRegistry.get_instance()
                                try:
                                    fallback = str(reg.resolve_project())
                                except Exception:
                                    fallback = str(Path.cwd().resolve())
                        kwargs["project_root"] = fallback

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    return fn(*args, **kwargs)
                return asyncio.run(fn(*args, **kwargs))
            finally:
                _explicit_project_root.reset(token)

        return caller
    return decorator


async def _resolve_context(
    ctx: Optional[Context] = None,
    project_root: Optional[Union[str, Path]] = None,
    filepath: Optional[str] = None,
) -> tuple[Path, Repository]:
    """Helper to resolve active workspace root and repository.

    1. Explicit project_root argument or internal override via contextvar.
    2. Primary: MCP client workspace roots via ctx.session.list_roots() (if supported).
    3. Filepath ancestry check for .arch/arch.db (for absolute filepaths).
    4. Fallback to ProjectRegistry cascading resolution (active_project in ~/.arch/projects.json, CWD, etc.).
    """
    registry = ProjectRegistry.get_instance()

    # 1. Explicit internal override or parameter
    effective_root = project_root or _explicit_project_root.get()
    if effective_root:
        db_root = find_project_root_with_db(effective_root)
        if db_root is not None:
            return db_root, registry.get_repository(project_root=db_root)
        # If effective_root had no db, check if filepath is absolute and has a db
        if filepath and Path(filepath).is_absolute():
            fp_root = find_project_root_with_db(filepath)
            if fp_root is not None:
                return fp_root, registry.get_repository(project_root=fp_root)
        target = Path(effective_root).resolve()
        return target, registry.get_repository(project_root=target)

    # 2. Ask Antigravity/client for open workspaces via roots/list if supported
    if ctx is not None:
        try:
            session = ctx.session
            if session is not None:
                roots_result = await session.list_roots()
                roots = getattr(roots_result, "roots", []) or []
                for r in roots:
                    uri = str(getattr(r, "uri", ""))
                    if uri:
                        candidate = uri_to_path(uri)
                        db_root = find_project_root_with_db(candidate)
                        if db_root is not None:
                            return db_root, registry.get_repository(project_root=db_root)
                        if (candidate / ".arch" / "arch.db").exists():
                            return candidate, registry.get_repository(project_root=candidate)
        except Exception:
            pass

    # 3. Path from filepath hint
    if filepath:
        db_root = find_project_root_with_db(filepath)
        if db_root is not None:
            return db_root, registry.get_repository(project_root=db_root)

    # 4. ProjectRegistry resolution (server_config, active_project, CWD)
    resolved_root = registry.resolve_project(project_root=project_root, filepath=filepath)
    repository = registry.get_repository(project_root=resolved_root)
    return resolved_root, repository


def get_server_repository(
    project_root: Optional[Union[str, Path]] = None,
    filepath: Optional[Union[str, Path]] = None,
) -> Repository:
    """Get or create cached Repository from the ProjectRegistry."""
    registry = ProjectRegistry.get_instance()
    return registry.get_repository(project_root=project_root, filepath=filepath)


def close_server_connection():
    """Explicitly close all cached server database connections."""
    ProjectRegistry.reset_instance()


@_tool()
async def graph(
    project_root: str,
    output_path: Optional[str] = "circuit_board.html",
    scope: Optional[Union[str, List[str]]] = None,
    include_tests: bool = False,
    include_occurrences: bool = False,
    include_external: bool = False,
    include_parameters: bool = False,
    max_refs: Optional[int] = None,
    open_browser: bool = False,
    ctx: Context = None,
) -> str:
    """
    Builds the interactive Electronic PCB Circuit Diagram HTML architecture visualizer directly from the DuckDB index.
    Generates a standalone, zoomable HTML schematic visualizer representing modules, classes, and dependency traces.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    output_path: Destination HTML file path (defaults to <project_root>/circuit_board.html).
    scope: Directory or package scope filter (defaults to registered paths in .arch/config.json).
    include_tests: Include test files in the graph visualizer.
    include_occurrences: Include raw symbol occurrence vias.
    include_external: Include external third-party dependencies.
    include_parameters: Include parameter variable nodes.
    max_refs: Maximum reference occurrences per symbol.
    open_browser: Whether to open the generated HTML in the default web browser.
    """
    try:
        resolved_root, _ = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_graph(
            project_root=resolved_root,
            output_path=output_path,
            scope=scope,
            include_tests=include_tests,
            include_occurrences=include_occurrences,
            include_external=include_external,
            include_parameters=include_parameters,
            max_refs=max_refs,
            open_browser=open_browser,
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating architecture circuit visualizer: {e}"


@_tool()
async def lookup(target: Union[List[str], str], project_root: str, ctx: Context = None) -> str:
    """
    Resolves symbol and file locations, definitions, occurrences, and direct call relationships.
    Use this tool like a targeted search or symbol-aware grep to locate a specific node, symbol, function, or class across the codebase.
    target: Symbol name(s) or file path(s) to locate.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    """
    filepath_hint = target if isinstance(target, str) and ("/" in target or "\\" in target) else None
    try:
        _, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath_hint)
        return handle_lookup(target, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing index search: {e}"


@_tool()
async def context(filepaths: Union[List[str], str], project_root: str, ctx: Context = None) -> str:
    """
    Returns structural outlines, declared symbols, class/method signatures, and line ranges for specified files.
    Use this tool when you know something is located in a specific file but don't know which part.
    filepaths: File path or list of file paths to inspect.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    """
    filepath_hint = filepaths if isinstance(filepaths, str) else (filepaths[0] if filepaths else None)
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath_hint)
        return handle_context(filepaths, repository, project_root=resolved_root)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error retrieving context: {e}"


@_tool()
async def impact(symbol: str, project_root: str, max_depth: int = 3, ctx: Context = None) -> str:
    """
    Performs blast radius analysis by computing the transitive closure of upstream callers and downstream callees up to max_depth.
    Use this tool when evaluating the ripple effects of proposed refactors or deletions.
    symbol: Focal symbol identifier to analyze.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    max_depth: Maximum call graph traversal depth (default 3).
    """
    try:
        _, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_impact(symbol, max_depth, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error computing blast radius: {e}"


@_tool()
async def compile_context(
    symbol: str,
    project_root: str,
    radius: int = 2,
    direction: str = "downstream",
    resolution: str = "signature",
    out_filepath: Optional[str] = None,
    max_tokens: int = 4000,
    ctx: Context = None,
) -> str:
    """
    Compiles a bounded architectural context document by traversing the call graph neighborhood of a focal symbol.
    symbol: Focal symbol identifier.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    radius: Hop distance radius in call graph.
    direction: 'upstream', 'downstream', or 'both'.
    resolution: 'signature' or 'full'.
    out_filepath: Optional output destination markdown file.
    max_tokens: Maximum token budget.
    """
    direction = direction.lower()
    valid, msg = validate_direction(direction)
    if not valid:
        return f"Error: {msg}"

    resolution = resolution.lower()
    valid, msg = validate_resolution(resolution)
    if not valid:
        return f"Error: {msg}"

    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_compile_context(
            symbol, radius, direction, resolution, out_filepath, repository, resolved_root, max_tokens
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error compiling architectural context: {e}"


@_tool()
async def audit(project_root: str, ctx: Context = None) -> str:
    """
    Runs project-wide architectural boundary and layer compliance checks against configured rules.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    """
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_audit(repository, resolved_root)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running audit: {e}"


@_tool()
async def report(name: str, project_root: str, format: str = "markdown", ctx: Context = None) -> str:
    """
    Generates high-level summaries or compliance reports of the workspace code graph.
    name: 'overview' or 'compliance'
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    format: 'markdown' or 'json'
    """
    try:
        _, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        from reporter.generator import Reporter
        reporter = Reporter(repository)
        return reporter.generate_report(name, format)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating report: {e}"


@_tool()
async def analyze(project_root: str, ctx: Context = None) -> str:
    """
    Validates architectural configuration ontology completeness, reachability, and referential sanity.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    """
    try:
        resolved_root, _ = await _resolve_context(ctx=ctx, project_root=project_root)
        from utils.arch_config import ArchConfig
        _, res = ArchConfig.parse_and_validate(resolved_root)
        lines = ["=== Configuration Sanity & Completeness Analysis ==="]
        if res["warnings"]:
            lines.append(f"\n[WARNING] Reachability warnings ({len(res['warnings'])}):")
            for w in res["warnings"]:
                lines.append(f"  - {w}")
        else:
            lines.append("\n[OK] Value reachability check passed (no unreachable values).")

        if res["errors"]:
            lines.append(f"\n[ERROR] Referential integrity failures ({len(res['errors'])}):")
            for err in res["errors"]:
                lines.append(f"  - {err}")
            lines.append("\nValidation failed.")
        else:
            lines.append("[OK] Referential integrity validation passed.")
            lines.append("\nValidation succeeded.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error analyzing configuration: {e}"


@_tool()
async def set_fields(
    filepath: str,
    fields_json: str,
    project_root: str,
    justification: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """
    Sets manual architectural metadata fields and tags for a registered file.
    filepath: Target file path.
    fields_json: JSON string of metadata key-values.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    justification: Optional reason for the update.
    """
    try:
        fields = json.loads(fields_json)
    except Exception as e:
        return f"Error: Invalid JSON fields payload: {e}"

    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath)
        from utils.session import resolve_filepath
        resolved = resolve_filepath(repository, filepath)
        if not resolved:
            return f"Error: File '{filepath}' is not registered in the database."

        file_info = repository.workspace.get_file(resolved)
        current_fields = {}
        if file_info and file_info.get("manual_fields"):
            mf = file_info["manual_fields"]
            if isinstance(mf, dict):
                current_fields = dict(mf)
            else:
                try:
                    current_fields = json.loads(mf)
                except Exception:
                    pass

        for k, v in fields.items():
            if v is None:
                current_fields.pop(k, None)
            else:
                current_fields[k] = v

        repository.workspace.set_manual_fields(resolved, current_fields, justification)
        from auditor.analyzer import Auditor
        auditor = Auditor(repository, resolved_root)
        auditor.run_audit()
        return f"Successfully updated manual fields for '{resolved}' to: {current_fields}."
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting fields: {e}"


@_tool()
async def clear_pending(justification: str, project_root: str, ctx: Context = None) -> str:
    """
    Clears the pending audit flag on all files in the database.
    justification: Reason for clearing pending audits.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    """
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        repository.workspace.clear_all_pending_audits(justification)
        from auditor.analyzer import Auditor
        auditor = Auditor(repository, resolved_root)
        auditor.run_audit()
        return "Successfully cleared pending audit status for all files."
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error clearing pending audits: {e}"


@_tool()
async def map(
    project_root: str,
    targets: Optional[Union[List[Dict[str, Any]], str]] = None,
    path: str = "",
    tree_depth: int = 1,
    detail_level: str = "folder",
    include_external: bool = False,
    ctx: Context = None,
) -> str:
    """
    Returns a structured, multi-level architectural blueprint map of the repository.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    targets: Optional target folder(s) or file pattern(s).
    path: Relative path within project to start mapping from.
    tree_depth: Depth of directory tree to include.
    detail_level: 'folder' or 'file'.
    include_external: Include external dependencies.
    """
    try:
        _, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=path or None)
        return handle_map(
            repository,
            targets=targets,
            path=path,
            tree_depth=tree_depth,
            detail_level=detail_level,
            include_external=include_external,
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error building architectural graph map: {e}"


@_tool()
async def set_status(
    filepath: str,
    status: str,
    project_root: str,
    justification: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """
    Sets manual AI logical compliance status for a file (COMPLIANT or VIOLATION_DETECTED).
    filepath: Target file path.
    status: 'COMPLIANT' or 'VIOLATION_DETECTED'.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    justification: Optional explanation for the status change.
    """
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath)
        return handle_set_status(repository, resolved_root, filepath, status, justification)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting status: {e}"


@_tool()
async def update(
    project_root: str,
    filepaths: Optional[Union[List[str], str]] = None,
    force: bool = False,
    ctx: Context = None,
) -> str:
    """
    Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges.
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
    filepaths: Optional specific file paths to re-index.
    force: Force full rebuild regardless of file modification timestamps.
    """
    filepath_hint = filepaths if isinstance(filepaths, str) else (filepaths[0] if filepaths else None)
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath_hint)
        return handle_update(repository, resolved_root, filepaths=filepaths, force=force)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error updating workspace: {e}"


def run_server(port: int = 0):
    try:
        if port > 0:
            if hasattr(mcp, "settings"):
                mcp.settings.port = port
            mcp.run(transport="sse")
        else:
            mcp.run()
    finally:
        WatcherManager.get_instance().stop_all()
        close_server_connection()


def main():
    run_server()


if __name__ == "__main__":
    main()
