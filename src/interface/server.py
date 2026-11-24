import asyncio
import functools
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import Context, FastMCP

from change_tracker.watcher_manager import WatcherManager
from db.repository import Repository
from interface.project_registry import ProjectRegistry, find_project_root_with_db
from interface.tools.analyze import handle_analyze
from interface.tools.audit import handle_audit
from interface.tools.clear_pending import handle_clear_pending
from interface.tools.clusters import handle_clusters
from interface.tools.compile_context import handle_compile_context
from interface.tools.context import handle_context
from interface.tools.graph import handle_graph
from interface.tools.history import handle_history
from interface.tools.impact import handle_impact
from interface.tools.lookup import handle_lookup
from interface.tools.map import handle_map
from interface.tools.query import handle_query
from interface.tools.set_fields import handle_set_fields
from interface.tools.set_status import handle_set_status
from interface.tools.update import handle_update
from interface.validators import (
    validate_cluster_unit,
    validate_cluster_view,
    validate_direction,
    validate_resolution,
    validate_sections,
)

mcp = FastMCP("arch")


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
    """Registers an async tool with FastMCP while permitting direct synchronous invocation."""
    def decorator(fn):
        mcp.tool()(fn)

        @functools.wraps(fn)
        def caller(*args, **kwargs):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                return fn(*args, **kwargs)
            return asyncio.run(fn(*args, **kwargs))

        return caller
    return decorator


async def _resolve_context(
    ctx: Optional[Context] = None,
    project_root: Optional[Union[str, Path]] = None,
    filepath: Optional[str] = None,
) -> tuple[Path, Repository]:
    """Resolves active workspace root and repository."""
    registry = ProjectRegistry.get_instance()

    if project_root:
        db_root = find_project_root_with_db(project_root)
        if db_root is not None:
            return db_root, registry.get_repository(project_root=db_root)
        if filepath and Path(filepath).is_absolute():
            fp_root = find_project_root_with_db(filepath)
            if fp_root is not None:
                return fp_root, registry.get_repository(project_root=fp_root)
        target = Path(project_root).resolve()
        return target, registry.get_repository(project_root=target)

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

    if filepath:
        db_root = find_project_root_with_db(filepath)
        if db_root is not None:
            return db_root, registry.get_repository(project_root=db_root)

    resolved_root = registry.resolve_project(project_root=project_root, filepath=filepath)
    repository = registry.get_repository(project_root=resolved_root)
    return resolved_root, repository


def get_server_repository(
    project_root: Optional[Union[str, Path]] = None,
    filepath: Optional[Union[str, Path]] = None,
) -> Repository:
    """Get or create cached Repository from the ProjectRegistry."""
    return ProjectRegistry.get_instance().get_repository(project_root=project_root, filepath=filepath)


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
    project_root: Root workspace path of the project containing .arch/arch.db (mandatory).
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
async def impact(
    symbol: str,
    project_root: str,
    max_depth: int = 4,
    direction: str = "upstream",
    max_nodes: int = 50,
    ctx: Context = None,
) -> str:
    """
    Performs blast radius analysis by computing the transitive call tree up to max_depth,
    enriched with live Git hotspot risk and Lift-ranked temporal co-change coupling for the focal file.
    """
    direction = direction.lower()
    valid, msg = validate_direction(direction)
    if not valid:
        return f"Error: {msg}"

    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_impact(
            symbol,
            max_depth,
            repository,
            direction=direction,
            max_nodes=max_nodes,
            project_root=resolved_root,
        )
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
async def audit(project_root: str, summary_only: bool = False, ctx: Context = None) -> str:
    """
    Runs project-wide architectural boundary and layer compliance checks against configured rules,
    returning a compact compliance scorecard plus concrete violation traces.
    """
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_audit(repository, resolved_root, summary_only=summary_only)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running audit: {e}"


@_tool()
async def history(
    project_root: str,
    sections: Optional[Union[List[str], str]] = None,
    target: Optional[str] = None,
    scope: Optional[Union[str, List[str]]] = None,
    commits: int = 100,
    limit: int = 10,
    ctx: Context = None,
) -> str:
    """
    Performs on-the-fly Git evolution and risk intelligence intersected with the static code graph.
    """
    valid, parsed = validate_sections(sections, has_target=bool(target))
    if not valid:
        return f"Error: {parsed}"

    try:
        filepath_hint = target if isinstance(target, str) and ("/" in target or "\\" in target) else None
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath_hint)
        return handle_history(
            repository=repository,
            project_root=resolved_root,
            sections=parsed,
            target=target,
            scope=scope,
            commits=commits,
            limit=limit,
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running git history analysis: {e}"


@_tool()
async def analyze(project_root: str, ctx: Context = None) -> str:
    """Validates architectural configuration ontology completeness, reachability, and referential sanity."""
    try:
        resolved_root, _ = await _resolve_context(ctx=ctx, project_root=project_root)
        report_text, _ = handle_analyze(resolved_root)
        return report_text
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
    """Sets manual architectural metadata fields and tags for a registered file."""
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath)
        msg, _ = handle_set_fields(repository, resolved_root, filepath, fields_json, justification)
        return msg
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting fields: {e}"


@_tool()
async def clear_pending(justification: str, project_root: str, ctx: Context = None) -> str:
    """Clears the pending audit flag on all files in the database."""
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_clear_pending(repository, resolved_root, justification)
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
    """Returns a structured, multi-level architectural blueprint map of the repository."""
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
    """Sets manual AI logical compliance status for a file (COMPLIANT or VIOLATION_DETECTED)."""
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath)
        msg, _ = handle_set_status(repository, resolved_root, filepath, status, justification)
        return msg
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
    """Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges."""
    filepath_hint = filepaths if isinstance(filepaths, str) else (filepaths[0] if filepaths else None)
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath_hint)
        return handle_update(repository, resolved_root, filepaths=filepaths, force=force)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error updating workspace: {e}"


@_tool()
async def query(
    sql: str,
    project_root: str,
    limit: Optional[int] = None,
    output_path: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """
    Executes a read-only SQL query directly against the DuckDB index (.arch/arch.db).
    Tables:
    - files (filepath, sha256, ast_sha256, language, status, manual_status, pending_audit, manual_fields, justification)
    - symbols (symbol, name, scip_id, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, classification, change_count, start_line, start_col, end_line, end_col)
    - edges (source, target, relation, weight, call_line)
    - occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
    - compliance_rules (rule_id, description, severity)
    - compliance_violations (violation_id, rule_id, symbol, filepath, line, message, origin)
    - diagnostics (filepath, symbol, line, col, severity, code, message, tags)
    - system_metadata (key, value)
    """
    try:
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root)
        return handle_query(
            repository=repository,
            project_root=resolved_root,
            sql=sql,
            limit=limit,
            output_path=output_path,
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing query: {e}"


@_tool()
async def clusters(
    project_root: str,
    cluster: Optional[str] = None,
    depth: int = 2,
    unit: str = "symbol",
    view: str = "both",
    scope: Optional[Union[str, List[str]]] = None,
    language: Optional[str] = None,
    include_tests: bool = False,
    include_drift: bool = True,
    ctx: Context = None,
) -> str:
    """
    Performs parameter-free hierarchical graph clustering, containment scoring, and architectural drift diagnostics.
    cluster: Cluster ID (e.g. 'c1', 'c2.1'), target symbol/file, 'residuals', 'unreferenced', or None for root overview.
    depth: Hierarchy expansion depth below focal cluster (default: 2).
    unit: 'symbol' (default) or 'file'.
    view: 'both' (default), 'summary', 'tree', or 'mermaid'.
    """
    ok_v, view_or_err = validate_cluster_view(view)
    if not ok_v:
        return f"Error: {view_or_err}"

    ok_u, unit_or_err = validate_cluster_unit(unit)
    if not ok_u:
        return f"Error: {unit_or_err}"

    try:
        depth_val = int(depth)
        if depth_val < 1:
            return "Error: Depth must be an integer >= 1."
    except (ValueError, TypeError):
        return f"Error: Invalid depth value: '{depth}'. Must be an integer >= 1."

    try:
        filepath_hint = (
            cluster
            if isinstance(cluster, str) and (
                "/" in cluster
                or "\\" in cluster
                or cluster.endswith((".dart", ".py", ".rs", ".go", ".ts", ".js"))
            )
            else None
        )
        resolved_root, repository = await _resolve_context(ctx=ctx, project_root=project_root, filepath=filepath_hint)
        return handle_clusters(
            repository=repository,
            project_root=resolved_root,
            cluster=cluster,
            depth=depth_val,
            unit=unit_or_err,
            view=view_or_err,
            scope=scope,
            language=language,
            include_tests=include_tests,
            include_drift=include_drift,
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running cluster analysis: {e}"


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
