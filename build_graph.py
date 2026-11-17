#!/usr/bin/env python3
"""
Executable entry point for the Arch PCB Circuit Board HTML Graph Builder.
Directly reads the DuckDB database and generates a zoom-able electronic motherboard schematic.
"""

import argparse
import os
import sys

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from graph_builder.cli import build_graph_html


def main():
    parser = argparse.ArgumentParser(
        description="Build an electronic PCB circuit diagram HTML visualizer directly from DuckDB."
    )
    parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    parser.add_argument("--db", default=None, help="Path to DuckDB file")
    parser.add_argument("-o", "--output", default="circuit_board.html", help="Path for output HTML file")
    parser.add_argument("-c", "--config", default=None, help="Path to circuit_config.json")
    parser.add_argument("--scope", default="src", help="Filter to a directory or file prefix")
    parser.add_argument("--include-tests", action="store_true", help="Include test files")
    parser.add_argument("--include-occurrences", action="store_true", help="Include raw occurrence vias")
    parser.add_argument("--include-external", action="store_true", help="Include external third-party symbols")
    parser.add_argument("--include-parameters", action="store_true", help="Include parameter variable nodes")
    parser.add_argument("--max-refs", type=int, default=None, help="Max reference occurrences per symbol")
    parser.add_argument("--open", action="store_true", help="Open in default web browser upon completion")

    args = parser.parse_args()
    db_path = args.db or os.path.join(args.project_root, ".arch", "arch.db")
    config_path = args.config
    if not config_path:
        cand = os.path.join(args.project_root, "circuit_config.json")
        if os.path.exists(cand):
            config_path = cand

    build_graph_html(
        db_path=db_path,
        output_path=args.output,
        include_occurrences=args.include_occurrences,
        max_refs_per_symbol=args.max_refs,
        include_external=args.include_external,
        exclude_tests=not args.include_tests,
        exclude_parameters=not args.include_parameters,
        scope=args.scope,
        config_path=config_path,
        open_browser=args.open,
    )


if __name__ == "__main__":
    main()
