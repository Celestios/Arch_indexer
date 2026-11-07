import os
import sys
from pathlib import Path
from typing import Optional, List, Union

# Setup sys.path to resolve imports from src/
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import FastMCP
from utils.session import db_session
from interface.server_config import get_project_root, get_db_path
from interface.tools.context import handle_context
from interface.tools.lookup import handle_lookup
from interface.tools.impact import handle_impact
from interface.tools.audit import handle_audit
from interface.tools.compile_context import handle_compile_context
from interface.validators import validate_direction, validate_resolution

mcp = FastMCP("arch")


@mcp.tool()
def lookup(target: Union[List[str], str]) -> str:
    """
    Resolves symbol/file locations, definitions, occurrences, and call relationships.
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
def context(filepaths: Union[List[str], str]) -> str:
    """
    Returns class/function signature outlines and line ranges for the specified file(s).
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
def compile_context(
    symbol: str,
    radius: int = 2,
    direction: str = "downstream",
    resolution: str = "signature",
    out_filepath: Optional[str] = None,
) -> str:
    """
    Compiles a deterministic markdown-formatted architectural context document
    starting from a focal symbol, traversing its call graph neighborhood.
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
        with db_session(get_project_root()) as (repository, db_conn):
            return handle_compile_context(
                symbol, radius, direction, resolution, out_filepath, repository, get_project_root()
            )
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error compiling architectural context: {e}"


@mcp.tool()
def audit() -> str:
    """
    Runs the project-wide architectural boundary rules compliance audit against config.json.
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
        return f"Error running audit: {e}"


def run_server(port: int = 0):
    if port > 0:
        mcp.run(transport="sse", port=port)
    else:
        mcp.run()


def main():
    run_server()


if __name__ == "__main__":
    main()

