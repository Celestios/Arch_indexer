import os
import sys
import json
from pathlib import Path
from typing import Optional, List, Union, Dict, Any

# Setup sys.path to resolve imports from src/
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import FastMCP
from db.repository import Repository
from interface.project_registry import ProjectRegistry
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


def _resolve_context(
    project_root: Optional[str] = None,
    filepath: Optional[str] = None,
) -> tuple[Path, Repository]:
    """Helper to resolve project root and active repository."""
    registry = ProjectRegistry.get_instance()
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


@mcp.tool()
def graph(
    project_root: Optional[str] = None,
    output_path: Optional[str] = "circuit_board.html",
    scope: Optional[str] = "src",
    include_tests: bool = False,
    include_occurrences: bool = False,
    include_external: bool = False,
    include_parameters: bool = False,
    max_refs: Optional[int] = None,
    open_browser: bool = False,
) -> str:
    """
    Builds the interactive Electronic PCB Circuit Diagram HTML architecture visualizer directly from the DuckDB index.
    Generates a standalone, zoomable HTML schematic visualizer representing modules, classes, and dependency traces.
    project_root: Optional target workspace root directory.
    output_path: Destination HTML file path (defaults to <project_root>/circuit_board.html).
    scope: Directory or package scope filter (default: "src").
    include_tests: Include test files in the graph visualizer.
    include_occurrences: Include raw symbol occurrence vias.
    include_external: Include external third-party dependencies.
    include_parameters: Include parameter variable nodes.
    max_refs: Maximum reference occurrences per symbol.
    open_browser: Whether to open the generated HTML in the default web browser.
    """
    try:
        resolved_root, _ = _resolve_context(project_root=project_root)
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


@mcp.tool()
def lookup(target: Union[List[str], str], project_root: Optional[str] = None) -> str:
    """
    Resolves symbol and file locations, definitions, occurrences, and direct call relationships.
    Use this tool like a targeted search or symbol-aware grep to locate a specific node, symbol, function, or class across the codebase.
    project_root: Optional workspace root directory.
    """
    filepath_hint = target if isinstance(target, str) and ("/" in target or "\\" in target) else None
    try:
        _, repository = _resolve_context(project_root=project_root, filepath=filepath_hint)
        return handle_lookup(target, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing index search: {e}"


@mcp.tool()
def context(filepaths: Union[List[str], str], project_root: Optional[str] = None) -> str:
    """
    Returns structural outlines, declared symbols, class/method signatures, and line ranges for specified files.
    Use this tool when you know something is located in a specific file but don't know which part.
    project_root: Optional workspace root directory.
    """
    filepath_hint = filepaths if isinstance(filepaths, str) else (filepaths[0] if filepaths else None)
    try:
        _, repository = _resolve_context(project_root=project_root, filepath=filepath_hint)
        return handle_context(filepaths, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error retrieving context: {e}"


@mcp.tool()
def impact(symbol: str, max_depth: int = 3, project_root: Optional[str] = None) -> str:
    """
    Performs blast radius analysis by computing the transitive closure of upstream callers and downstream callees up to max_depth.
    Use this tool when evaluating the ripple effects of proposed refactors or deletions.
    project_root: Optional workspace root directory.
    """
    try:
        _, repository = _resolve_context(project_root=project_root)
        return handle_impact(symbol, max_depth, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error computing blast radius: {e}"


@mcp.tool()
def compile_context(
    symbol: str,
    radius: int = 2,
    direction: str = "downstream",
    resolution: str = "signature",
    out_filepath: Optional[str] = None,
    max_tokens: int = 4000,
    project_root: Optional[str] = None,
) -> str:
    """
    Compiles a bounded architectural context document by traversing the call graph neighborhood of a focal symbol.
    project_root: Optional workspace root directory.
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
        resolved_root, repository = _resolve_context(project_root=project_root)
        return handle_compile_context(
            symbol, radius, direction, resolution, out_filepath, repository, resolved_root, max_tokens
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error compiling architectural context: {e}"


@mcp.tool()
def audit(project_root: Optional[str] = None) -> str:
    """
    Runs project-wide architectural boundary and layer compliance checks against configured rules.
    project_root: Optional workspace root directory.
    """
    try:
        resolved_root, repository = _resolve_context(project_root=project_root)
        return handle_audit(repository, resolved_root)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running audit: {e}"


@mcp.tool()
def report(name: str, format: str = "markdown", project_root: Optional[str] = None) -> str:
    """
    Generates high-level summaries or compliance reports of the workspace code graph.
    name: 'overview' or 'compliance'
    format: 'markdown' or 'json'
    project_root: Optional workspace root directory.
    """
    try:
        _, repository = _resolve_context(project_root=project_root)
        from reporter.generator import Reporter
        reporter = Reporter(repository)
        return reporter.generate_report(name, format)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating report: {e}"


@mcp.tool()
def analyze(project_root: Optional[str] = None) -> str:
    """
    Validates architectural configuration ontology completeness, reachability, and referential sanity.
    project_root: Optional workspace root directory.
    """
    try:
        resolved_root, _ = _resolve_context(project_root=project_root)
        from auditor.validator import ConfigValidator
        validator = ConfigValidator(resolved_root)
        res = validator.validate()
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


@mcp.tool()
def set_fields(
    filepath: str,
    fields_json: str,
    justification: Optional[str] = None,
    project_root: Optional[str] = None,
) -> str:
    """
    Sets manual architectural metadata fields and tags for a registered file.
    project_root: Optional workspace root directory.
    """
    try:
        fields = json.loads(fields_json)
    except Exception as e:
        return f"Error: Invalid JSON fields payload: {e}"

    try:
        resolved_root, repository = _resolve_context(project_root=project_root, filepath=filepath)
        from utils.session import resolve_filepath
        resolved = resolve_filepath(repository, filepath)
        if not resolved:
            return f"Error: File '{filepath}' is not registered in the database."

        file_info = repository.files.get_file(resolved)
        current_fields = {}
        if file_info and file_info.get("manual_fields"):
            try:
                current_fields = json.loads(file_info["manual_fields"])
            except Exception:
                pass

        for k, v in fields.items():
            if v is None:
                current_fields.pop(k, None)
            else:
                current_fields[k] = v

        repository.files.update_file_manual_fields(resolved, current_fields, justification)
        from auditor.analyzer import Auditor
        auditor = Auditor(repository, resolved_root)
        auditor.run_audit()
        return f"Successfully updated manual fields for '{resolved}' to: {current_fields}."
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting fields: {e}"


@mcp.tool()
def clear_pending(justification: str, project_root: Optional[str] = None) -> str:
    """
    Clears the pending audit flag on all files in the database.
    project_root: Optional workspace root directory.
    """
    try:
        resolved_root, repository = _resolve_context(project_root=project_root)
        repository.files.clear_all_pending_audits(justification)
        from auditor.analyzer import Auditor
        auditor = Auditor(repository, resolved_root)
        auditor.run_audit()
        return "Successfully cleared pending audit status for all files."
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error clearing pending audits: {e}"


@mcp.tool()
def clear_pending_audits(justification: str = "Manual clear", project_root: Optional[str] = None) -> str:
    """Alias for clear_pending."""
    return clear_pending(justification, project_root=project_root)


@mcp.tool()
def map(
    targets: Optional[Union[List[Dict[str, Any]], str]] = None,
    path: str = "",
    tree_depth: int = 1,
    detail_level: str = "folder",
    include_external: bool = False,
    project_root: Optional[str] = None,
) -> str:
    """
    Returns a structured, multi-level architectural blueprint map of the repository.
    project_root: Optional workspace root directory.
    """
    try:
        _, repository = _resolve_context(project_root=project_root, filepath=path or None)
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


@mcp.tool()
def set_status(
    filepath: str,
    status: str,
    justification: Optional[str] = None,
    project_root: Optional[str] = None,
) -> str:
    """
    Sets manual AI logical compliance status for a file (COMPLIANT or VIOLATION_DETECTED).
    project_root: Optional workspace root directory.
    """
    try:
        resolved_root, repository = _resolve_context(project_root=project_root, filepath=filepath)
        return handle_set_status(repository, resolved_root, filepath, status, justification)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting status: {e}"


@mcp.tool()
def update(
    filepaths: Optional[Union[List[str], str]] = None,
    force: bool = False,
    project_root: Optional[str] = None,
) -> str:
    """
    Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges.
    project_root: Optional workspace root directory.
    """
    filepath_hint = filepaths if isinstance(filepaths, str) else (filepaths[0] if filepaths else None)
    try:
        resolved_root, repository = _resolve_context(project_root=project_root, filepath=filepath_hint)
        return handle_update(repository, resolved_root, filepaths=filepaths, force=force)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error updating workspace: {e}"


# Backward compatibility aliases for internal python calls
def reindex(filepaths: Optional[Union[List[str], str]] = None, force: bool = False, project_root: Optional[str] = None) -> str:
    return update(filepaths=filepaths, force=force, project_root=project_root)


def index(filepaths: Optional[Union[List[str], str]] = None, force: bool = False, project_root: Optional[str] = None) -> str:
    return update(filepaths=filepaths, force=force, project_root=project_root)


def run_server(port: int = 0):
    try:
        # Pre-register default project root if available
        default_root = get_default_project_root()
        if (default_root / ".arch" / "arch.db").exists():
            try:
                registry = ProjectRegistry.get_instance()
                registry.register_project(default_root, start_watcher=True)
            except Exception:
                pass

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
