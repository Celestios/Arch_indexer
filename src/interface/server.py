import os
import sys
from pathlib import Path
from typing import Optional, List, Union

# Setup sys.path to resolve imports from src/
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import FastMCP
from engines.embedder import LocalEmbedder
from utils.session import db_session
from interface.server_config import get_project_root, get_arch_dir, get_db_path, get_bin_dir

from interface.tools.query import handle_query
from interface.tools.context import handle_context
from interface.tools.lookup import handle_lookup
from interface.tools.impact import handle_impact
from interface.tools.audit import handle_audit
from interface.tools.map import handle_map
from interface.tools.trace import handle_trace
from interface.tools.report import handle_report
from interface.tools.set_fields import handle_set_fields
from interface.tools.clear_pending_audits import handle_clear_pending_audits
from interface.tools.compile_context import handle_compile_context
from interface.tools.analyze import handle_analyze


mcp = FastMCP("arch")


@mcp.tool()
def query(text: Union[List[str], str], limit: int = 5) -> str:
    """
    Runs keyword and semantic searches over symbols, docstrings, and files in the codebase.
    Accepts a single query string or a list of query strings, returning matches for each.

    Best Practice: Use multiple, focused search terms (e.g. as a list of strings) instead
    of a single string combined with logical operators like "and" or "or". Use this tool to
    discover target symbols or files before reading them.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        embedder = LocalEmbedder(get_bin_dir())
    except Exception as e:
        return f"Error: Could not initialize embedding engine: {e}"

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_query(text, limit, repository, embedder)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing query search: {e}"


@mcp.tool()
def context(filepaths: Union[List[str], str]) -> str:
    """
    Provides a compact structural index (Table of Contents) of all classes, methods,
    and functions declared in the specified file(s), along with their precise line ranges.
    Use this to locate specific definitions before reading the code.

    Guidelines:
      - Always call this tool before reading the contents of a file to locate definitions
        and identify line ranges to check, especially for large files.
      - Pass multiple file paths to this tool when scanning or locating paths that implement
        a specific interface or package feature.

    Accepts:
      - A single filepath string
      - A comma-separated filepath string (e.g. 'file1.dart, file2.dart')
      - A list/array of filepaths
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_context(filepaths, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error retrieving context: {e}"


@mcp.tool()
def impact(symbol: str, max_depth: int = 3) -> str:
    """
    Performs blast radius analysis for a symbol by computing the transitive closure
    of its upstream callers and downstream callees up to max_depth.
    Use this to see what will break if you modify this symbol's signature.

    Guidelines:
      - Use when editing critical/central code, or before modifying interfaces/signatures
        that control many downstream targets, to understand what components the change
        might impact and prevent regressions.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_impact(symbol, max_depth, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error computing blast radius: {e}"


@mcp.tool()
def audit() -> str:
    """
    Runs the project-wide architectural boundary rules compliance audit based on Layer/Tier rules in config.json.

    Guidelines:
      - This tool operates on the architectural rules database. Run this tool only when explicitly
        prompted/instructed by the user or other skills.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_audit(repository, get_project_root())
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running compliance audit: {e}"


@mcp.tool()
def map() -> str:
    """
    Provides a high-level architectural map of the repository, including total counts,
    automatically detected symbol communities (using Label Propagation), inter-module call weights,
    and the most connected hub symbols in each community.

    Guidelines:
      - Use map at the start of a task when no information for the project is available.
        It gives a bird's-eye view of the project and module dependencies.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_map(repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error building architectural graph map: {e}"


@mcp.tool()
def trace(source: str, sink: str) -> str:
    """
    Traces the data flow path from a source symbol to a sink symbol.
    Combines Dart analyzer + CodeQL + FFI_Binds for cross-language tracing.
    Returns a Markdown representation of the flow path.

    Guidelines:
      - This tool is especially useful when fixing bugs. Use it to trace data flows and understand
        exactly where to place debugging print/log statements or checks.
      - Supports cross-language traces: any language -> FFI -> any other language
      - Auto-detects languages from symbol names or file paths
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_trace(source, sink, repository, get_arch_dir(), get_bin_dir)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error running data flow trace: {e}"


@mcp.tool()
def report(name: str, format: str = "markdown") -> str:
    """
    Generates a structured workspace report.
    Parameters:
      name: The name of the report ('overview' or 'compliance').
      format: The output format ('markdown' or 'json', default: 'markdown').

    Guidelines:
      - Similar to compile_context, but provides less direct control and a broader view of
        the workspace across different aspects.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_report(name, format, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error generating report: {e}"


@mcp.tool()
def set_fields(
    target: str,
    update: Optional[str] = None,
    justification: Optional[str] = None,
) -> str:
    """
    Updates manual compliance status or manual metadata fields for files.
    Enforces the configuration ontology strictly from config.json.

    Parameters:
      target: Either a JSON filepath (for batch updates) or a source filepath.
      update: Optional. Combined field and value string in the format "field:value".
              Example: "status:VIOLATION" or "pattern:Controller".
      justification: Optional. Explanatory comment for the status update (required if status is VIOLATION).

    Guidelines:
      - This tool operates on config.json compliance flags and statuses. Run this tool only
        when instructed by the user's prompt or other skills on how and where to use it.
      - Negative Constraint: Do NOT modify the ontology config.json file directly without
        first consulting the user.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_set_fields(target, update, justification, repository, get_project_root())
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error updating fields: {e}"


@mcp.tool()
def clear_pending_audits() -> str:
    """
    Clears the pending audit flags for all files in the database.
    Use this after large refactors or git checkout operations when you know the changes are compliant.

    Guidelines:
      - This tool operates on the database's compliance state. Run this tool only when instructed
        by the user's prompt or other skills on how and where to use it.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_clear_pending_audits(repository, get_project_root())
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error clearing pending audits: {e}"


@mcp.tool()
def lookup(target: str) -> str:
    """
    Looks up details, metadata, and relationships for a file module or code symbol.
    The tool automatically detects whether the target is a file path (e.g. 'auditor.analyzer'
    or 'src/auditor/analyzer.py') or a code symbol (e.g. 'auditor.analyzer.Auditor.run_audit').

    Guidelines:
      - Use to retrieve symbol definitions, occurrences, and relationships for any target symbol
        or file module before reading or modifying it.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_lookup(target, repository)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing index search: {e}"


@mcp.tool()
def compile_context(
    symbol: str,
    radius: int = 2,
    direction: str = "downstream",
    resolution: str = "full",
    out_filepath: Optional[str] = None,
) -> str:
    """
    Compiles a deterministic markdown-formatted architectural context document
    starting from a focal symbol, traversing its call graph neighborhood.
    Use this to see caller/callee implementations and metadata.

    Parameters:
      symbol: The name of the focal symbol to start compilation from.
      radius: Traversal depth / number of hops along the call graph (default: 2).
      direction: Traversal direction: 'downstream' (callees), 'upstream' (callers), or 'both' (default: 'downstream').
      resolution: Neighbors detail level: 'full' (include complete code bodies) or 'signature' (signatures & docstrings only) (default: 'full').
      out_filepath: Optional path (relative to project root) to write the compiled context markdown to.

    Guidelines:
      - Use in different kinds of scenarios, such as when you want to explain code logic,
        generate a recap, or compile comprehensive context for code modifications.
      - Negative Constraint: Do NOT run this tool with a radius > 2 or resolution='full' unless
        necessary, as it rapidly consumes the token context window budget.
    """
    direction = direction.lower()
    if direction not in ("upstream", "downstream", "both"):
        return f"Error: Invalid direction: '{direction}'. Allowed: upstream, downstream, both."

    resolution = resolution.lower()
    if resolution not in ("full", "signature"):
        return f"Error: Invalid resolution: '{resolution}'. Allowed: full, signature."

    db_path = get_db_path()
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' first."

    try:
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_compile_context(
                symbol, radius, direction, resolution, out_filepath, repository, get_project_root()
            )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error compiling architectural context: {e}"


@mcp.tool()
def analyze() -> str:
    """
    Validates the architectural configuration ontology (config.json) completeness and sanity.
    Checks syntax, structure, allowed values reachability, dependency rules referential integrity,
    and propagation barriers validation. Returns a Markdown report summarizing issues.

    Guidelines:
      - Use this tool ONLY after modifying the ontology configuration file (config.json) to
        validate its completeness and sanity.
    """
    return handle_analyze(get_project_root())


def _filter_blank_stdin() -> None:
    """Filter blank lines from stdin before MCP reads it."""
    import threading

    try:
        r_fd, w_fd = os.pipe()
        saved_fd = os.dup(sys.stdin.fileno())

        def _relay() -> None:
            try:
                with open(saved_fd, "rb") as src, open(w_fd, "wb") as dst:
                    for line in src:
                        if line.strip():
                            dst.write(line)
                            dst.flush()
            except Exception:
                pass

        threading.Thread(target=_relay, daemon=True).start()
        os.dup2(r_fd, sys.stdin.fileno())
        os.close(r_fd)
        sys.stdin = open(0, "r", closefd=False)
    except Exception:
        pass


def run_server():
    _filter_blank_stdin()
    mcp.run()


if __name__ == "__main__":
    run_server()
