"""MCP tool handler for building the interactive Electronic PCB Circuit Diagram HTML visualizer."""
import contextlib
import os
import sys
from pathlib import Path
from typing import Optional


def handle_graph(
    project_root: Path,
    output_path: Optional[str] = None,
    scope: Optional[str] = "src",
    include_tests: bool = False,
    include_occurrences: bool = False,
    include_external: bool = False,
    include_parameters: bool = False,
    max_refs: Optional[int] = None,
    open_browser: bool = False,
) -> str:
    """Builds the interactive Electronic PCB Circuit Diagram HTML visualizer from DuckDB."""
    db_path = project_root / ".arch" / "arch.db"
    if not db_path.exists():
        return f"Error: Arch database not found at {db_path}. Please run 'arch init' in '{project_root}' first."

    config_path: Optional[str] = None
    candidate = project_root / "circuit_config.json"
    if candidate.exists():
        config_path = str(candidate)

    out_file = output_path or "circuit_board.html"
    if not os.path.isabs(out_file):
        out_file = str(project_root / out_file)

    try:
        from graph_builder.cli import build_graph_html

        # Redirect stdout to stderr to protect stdio JSON-RPC streams
        with contextlib.redirect_stdout(sys.stderr):
            abs_output = build_graph_html(
                db_path=str(db_path),
                output_path=out_file,
                include_occurrences=include_occurrences,
                max_refs_per_symbol=max_refs,
                include_external=include_external,
                exclude_tests=not include_tests,
                exclude_parameters=not include_parameters,
                scope=scope,
                config_path=config_path,
                open_browser=open_browser,
            )

        return f"Successfully generated architecture circuit visualizer at: {abs_output}"
    except Exception as e:
        return f"Error generating architecture circuit visualizer: {e}"
