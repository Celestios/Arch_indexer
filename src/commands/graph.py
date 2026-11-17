"""
CLI Command to generate the Electronic PCB Circuit Diagram HTML Visualizer.
"""

import os
from graph_builder.cli import build_graph_html
from utils.session import get_project_root


def register(subparsers):
    p = subparsers.add_parser(
        "graph",
        help="Build interactive PCB circuit board architecture visualizer directly from DuckDB",
    )
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.add_argument("--db", default=None, help="Path to DuckDB file (defaults to <project_root>/.arch/arch.db)")
    p.add_argument("-o", "--output", default="circuit_board.html", help="Path for output HTML file")
    p.add_argument("-c", "--config", default=None, help="Path to circuit_config.json")
    p.add_argument("--scope", default="src", help="Filter to a directory or file prefix")
    p.add_argument("--include-tests", action="store_true", help="Include test files")
    p.add_argument("--include-occurrences", action="store_true", help="Include raw occurrence vias")
    p.add_argument("--include-external", action="store_true", help="Include external third-party symbols")
    p.add_argument("--include-parameters", action="store_true", help="Include parameter variable nodes")
    p.add_argument("--max-refs", type=int, default=None, help="Max reference occurrences per symbol")
    p.add_argument("--open", action="store_true", help="Open in default web browser upon completion")
    p.set_defaults(func=cmd_graph)


def cmd_graph(args):
    """Generates the interactive electronic circuit board schematic HTML."""
    root = get_project_root(args)
    db_path = args.db
    if not db_path:
        db_path = os.path.join(root, ".arch", "arch.db")

    config_path = args.config
    if not config_path and root:
        candidate = os.path.join(root, "circuit_config.json")
        if os.path.exists(candidate):
            config_path = candidate

    output_path = args.output
    if not os.path.isabs(output_path) and root and root != ".":
        output_path = os.path.join(root, output_path)

    build_graph_html(
        db_path=db_path,
        output_path=output_path,
        include_occurrences=args.include_occurrences,
        max_refs_per_symbol=args.max_refs,
        include_external=args.include_external,
        exclude_tests=not args.include_tests,
        exclude_parameters=not args.include_parameters,
        scope=args.scope,
        config_path=config_path,
        open_browser=args.open,
    )
