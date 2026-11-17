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
from db.connection import DbConnection
from db.repository import Repository
from interface.server_config import get_project_root, get_db_path
from interface.tools.context import handle_context
from interface.tools.lookup import handle_lookup
from interface.tools.impact import handle_impact
from interface.tools.audit import handle_audit
from interface.tools.compile_context import handle_compile_context
from interface.tools.map import handle_map
from interface.tools.update import handle_update
from interface.tools.set_status import handle_set_status
from interface.validators import validate_direction, validate_resolution

mcp = FastMCP("arch")

_shared_db_conn: Optional[DbConnection] = None
_shared_repository: Optional[Repository] = None


def get_server_repository() -> Repository:
    """Get or create cached Repository/DbConnection for the MCP server lifecycle."""
    global _shared_db_conn, _shared_repository
    db_path = get_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Arch database not found at {db_path}. Please run 'arch init' first.")
    if _shared_db_conn is None or _shared_db_conn.db_path != db_path:
        if _shared_db_conn is not None:
            try:
                _shared_db_conn.close()
            except Exception:
                pass
        _shared_db_conn = DbConnection(db_path)
        _shared_repository = Repository(_shared_db_conn)
    return _shared_repository


def close_server_connection():
    """Explicitly close cached server database connection."""
    global _shared_db_conn, _shared_repository
    if _shared_db_conn is not None:
        try:
            _shared_db_conn.close()
        except Exception:
            pass
        _shared_db_conn = None
        _shared_repository = None


@mcp.tool()
def lookup(target: Union[List[str], str]) -> str:
    """
    Resolves symbol and file locations, definitions, occurrences, and direct call relationships.
    Use this tool like a targeted search or symbol-aware grep to locate a specific node, symbol, function, or class across the codebase when you don't know where it is defined or used.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        return handle_lookup(target, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing index search: {e}"


@mcp.tool()
def context(filepaths: Union[List[str], str]) -> str:
    """
    Returns structural outlines, declared symbols, class/method signatures, and line ranges for specified files.
    Use this tool when you know something is located in a specific file but don't know which part, allowing you to inspect its internal structure and locate the exact section or member without reading the entire file.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        return handle_context(filepaths, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error retrieving context: {e}"


@mcp.tool()
def impact(symbol: str, max_depth: int = 3) -> str:
    """
    Performs blast radius analysis by computing the transitive closure of upstream callers and downstream callees up to max_depth.
    Use this tool when evaluating the ripple effects of proposed refactors or deletions, tracing multi-hop failure propagation in defect investigations, assessing coupling between components, or discovering central hub symbols.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
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
) -> str:
    """
    Compiles a bounded architectural context document by traversing the call graph neighborhood of a focal symbol.
    Use this tool when assembling targeted multi-hop implementation or refactoring context around a focal point, analyzing vertical execution pipelines across architectural tiers, or conducting forensic defect slicing without manually reading multiple files.
    """
    direction = direction.lower()
    valid, msg = validate_direction(direction)
    if not valid:
        return f"Error: {msg}"

    resolution = resolution.lower()
    valid, msg = validate_resolution(resolution)
    if not valid:
        return f"Error: {msg}"

    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        return handle_compile_context(
            symbol, radius, direction, resolution, out_filepath, repository, get_project_root(), max_tokens
        )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error compiling architectural context: {e}"


@mcp.tool()
def audit() -> str:
    """
    Runs project-wide architectural boundary and layer compliance checks against configured rules.
    Use this tool when validating architectural boundaries, verifying that changes do not violate layer or module constraints, checking for circular dependencies, or enforcing structural integrity during code reviews and pre-commit checks.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        return handle_audit(repository, get_project_root())
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running audit: {e}"


@mcp.tool()
def report(name: str, format: str = "markdown") -> str:
    """
    Generates high-level summaries or compliance reports of the workspace code graph.
    name: 'overview' or 'compliance'
    format: 'markdown' or 'json'
    Use this tool when creating executive architectural overviews, summarizing structural metrics and active violations for documentation, or exporting workspace dependency health in Markdown or JSON format.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        from reporter.generator import Reporter
        reporter = Reporter(repository)
        return reporter.generate_report(name, format)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating report: {e}"


@mcp.tool()
def analyze() -> str:
    """
    Validates architectural configuration ontology completeness, reachability, and referential sanity.
    Use this tool when authoring or updating architectural boundary rules, checking configuration syntax and schema integrity, verifying layer and tier definitions, or troubleshooting rule misconfigurations.
    """
    try:
        from auditor.validator import ConfigValidator
        project_root = get_project_root()
        validator = ConfigValidator(project_root)
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
def set_fields(filepath: str, fields_json: str, justification: Optional[str] = None) -> str:
    """
    Sets manual architectural metadata fields and tags for a registered file.
    Use this tool when tagging files with custom architectural metadata, recording module classifications, assigning component responsibilities, or annotating files with inspection notes.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        fields = json.loads(fields_json)
    except Exception as e:
        return f"Error: Invalid JSON fields payload: {e}"

    try:
        repository = get_server_repository()
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
        auditor = Auditor(repository, get_project_root())
        auditor.run_audit()
        return f"Successfully updated manual fields for '{resolved}' to: {current_fields}."
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting fields: {e}"


@mcp.tool()
def clear_pending(justification: str) -> str:
    """
    Clears the pending audit flag on all files in the database.
    Use this tool when acknowledging recorded workspace modifications, resetting incremental audit queues after reviewing changes, or resetting change tracker flags.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        repository.files.clear_all_pending_audits(justification)
        from auditor.analyzer import Auditor
        auditor = Auditor(repository, get_project_root())
        auditor.run_audit()
        return "Successfully cleared pending audit status for all files."
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error clearing pending audits: {e}"


@mcp.tool()
def clear_pending_audits(justification: str = "Manual clear") -> str:
    """Alias for clear_pending. Use this tool when clearing pending audit flags across tracked files in the database."""
    return clear_pending(justification)


@mcp.tool()
def map(
    targets: Optional[Union[List[Dict[str, Any]], str]] = None,
    path: str = "",
    tree_depth: int = 1,
    detail_level: str = "folder",
    include_external: bool = False,
) -> str:
    """
    Returns a structured, multi-level architectural blueprint map of the repository, including project totals, structural nodes, key hubs, and directional call flows.
    Use this tool when exploring an unfamiliar codebase, understanding subsystem boundaries and topologies, discovering inter-module call dependencies, identifying central architectural hubs, or surveying code organization at configurable depths.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
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
def set_status(filepath: str, status: str, justification: Optional[str] = None) -> str:
    """
    Sets manual AI logical compliance status for a file (COMPLIANT or VIOLATION_DETECTED). Flagging a file as VIOLATION_DETECTED requires a justification.
    Use this tool when recording architectural review assessments, flagging logical violations or anti-patterns that static rules cannot detect, or approving documented architectural exceptions with justification.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        return handle_set_status(repository, get_project_root(), filepath, status, justification)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error setting status: {e}"


@mcp.tool()
def update(filepaths: Optional[Union[List[str], str]] = None, force: bool = False) -> str:
    """
    Triggers incremental or forced full synchronization of workspace symbols, relationships, and call graph edges.
    Note that the MCP watcher module already auto-updates the database in the background (tree-sitter updates are quick, while SCIP-gathered info might lag). Use this tool only for manual updates when forced synchronization or explicit re-indexing is required.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."
    try:
        repository = get_server_repository()
        return handle_update(repository, get_project_root(), filepaths=filepaths, force=force)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error updating workspace: {e}"


# Backward compatibility aliases for internal python calls (not exposed as MCP tools)
def reindex(filepaths: Optional[Union[List[str], str]] = None, force: bool = False) -> str:
    """Alias for update."""
    return update(filepaths=filepaths, force=force)


def index(filepaths: Optional[Union[List[str], str]] = None, force: bool = False) -> str:
    """Alias for update."""
    return update(filepaths=filepaths, force=force)


def run_server(port: int = 0):
    try:
        if port > 0:
            if hasattr(mcp, "settings"):
                mcp.settings.port = port
            mcp.run(transport="sse")
        else:
            mcp.run()
    finally:
        close_server_connection()


def main():
    run_server()


if __name__ == "__main__":
    main()

