#!/usr/bin/env python3
"""
Migration script to:
1. Move graph_builder into src/graph_builder using git mv.
2. Strip main() and CLI argument parsing from src/graph_builder/cli.py.
3. Create src/commands/graph.py registering 'graph' command.
4. Update build_graph.py root entrypoint.
5. Update method name formatting in scip_parser.py and model.py to strip className# prefix.
6. Update scripts/update_graph_builder.py paths.
"""

import os
import re
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def run_git_mv():
    src_gb = ROOT_DIR / "src" / "graph_builder"
    orig_gb = ROOT_DIR / "graph_builder"

    if orig_gb.exists() and not src_gb.exists():
        print("[*] Moving graph_builder to src/graph_builder via git mv...")
        subprocess.run(["git", "mv", "graph_builder", "src/graph_builder"], cwd=ROOT_DIR, check=True)
        print("[+] Successfully moved graph_builder to src/graph_builder")
    elif src_gb.exists():
        print("[*] src/graph_builder already exists, skipping git mv.")


def update_cli_py():
    cli_path = ROOT_DIR / "src" / "graph_builder" / "cli.py"
    if not cli_path.exists():
        raise FileNotFoundError(f"Missing {cli_path}")

    content = cli_path.read_text(encoding="utf-8")

    # Content without main() and argparse
    new_content = '''"""
Core Runner for the Modular Electronic Circuit Board HTML Graph Builder.
"""

import os
import webbrowser
from typing import Optional

from .config import CircuitConfig
from .ingestion.db_reader import DatabaseReader
from .domain.model import GraphModel
from .layout.circuit_layout import CircuitLayoutEngine
from .serialization.compressor import compress_circuit_data
from .renderer.html_generator import HtmlGraphGenerator


def build_graph_html(
    db_path: str = ".arch/arch.db",
    output_path: str = "circuit_board.html",
    include_occurrences: bool = False,
    max_refs_per_symbol: Optional[int] = None,
    include_external: bool = False,
    exclude_tests: bool = True,
    exclude_parameters: bool = True,
    scope: Optional[str] = "src",
    config_path: Optional[str] = None,
    open_browser: bool = False,
) -> str:
    cfg = CircuitConfig.load(config_path)
    effective_max_refs = max_refs_per_symbol if max_refs_per_symbol is not None else cfg.max_refs_per_symbol

    print(f"[*] Connecting to database: {db_path}")
    reader = DatabaseReader(db_path=db_path)
    stats = reader.get_summary_stats()
    print(
        f"[*] Workspace totals: {stats['files_count']} files, {stats['symbols_count']} symbols, "
        f"{stats['occurrences_count']} occurrences, {stats['edges_count']} edges"
    )

    print(f"[*] Building knowledge graph model (scope: {scope or 'all'}, exclude_tests: {exclude_tests})...")
    model = GraphModel(
        include_occurrences=include_occurrences,
        max_refs_per_symbol=effective_max_refs,
        include_external=include_external,
        exclude_tests=exclude_tests,
        exclude_parameters=exclude_parameters,
        scope=scope,
        hub_threshold=cfg.hub_threshold,
    )
    model.build_from_reader(reader)
    graph_dict = model.to_dict()
    graph_dict["scope"] = scope
    reader.close()

    node_count = len(graph_dict.get("nodes", []))
    edge_count = len(graph_dict.get("links", []))
    print(f"[*] Graph model created: {node_count} nodes, {edge_count} connections")

    print("[*] Computing Left-to-Right Directory Funnel & LCA Hierarchical Escape Routing...")
    layout_engine = CircuitLayoutEngine(config=cfg)
    circuit_data = layout_engine.apply_circuit_layout(graph_dict)
    pkg_count = len(circuit_data.get("packages", []))
    print(
        f"[*] Circuit mapped: {pkg_count} IC packages across "
        f"{len(circuit_data.get('zone_banners', []))} hierarchical folder zones"
    )

    print("[*] Applying compact encoding (interned strings, integer indexing, pre-routed waypoints)...")
    compact_data = compress_circuit_data(circuit_data)

    print(f"[*] Generating standalone HTML visualizer -> {output_path}...")
    generator = HtmlGraphGenerator()
    html_content = generator.generate_html(
        compact_data, title=f"Arch Architecture Circuit Board ({pkg_count} Modules)"
    )

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    abs_output = os.path.abspath(output_path)
    file_size_mb = os.path.getsize(abs_output) / (1024 * 1024)
    print(f"[+] Successfully generated: {abs_output} ({file_size_mb:.2f} MB)")

    if open_browser:
        print("[*] Opening in default web browser...")
        webbrowser.open(f"file://{abs_output}")

    return abs_output
'''
    cli_path.write_text(new_content, encoding="utf-8")
    print("[+] Stripped main and command line parsing from src/graph_builder/cli.py")


def create_command_graph_py():
    cmd_path = ROOT_DIR / "src" / "commands" / "graph.py"
    content = '''"""
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
'''
    cmd_path.write_text(content, encoding="utf-8")
    print(f"[+] Created {cmd_path}")


def update_build_graph_py():
    bg_path = ROOT_DIR / "build_graph.py"
    content = '''#!/usr/bin/env python3
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
'''
    bg_path.write_text(content, encoding="utf-8")
    print(f"[+] Updated {bg_path}")


def update_method_names():
    scip_parser_path = ROOT_DIR / "src" / "graph_builder" / "ingestion" / "scip_parser.py"
    content = scip_parser_path.read_text(encoding="utf-8")

    # Replace splitting on [/:#] so method names inside classes don't retain ClassName#
    old_target = """            display_name = clean_desc.rstrip("#/.")
            if clean_desc.endswith("()."):
                base = clean_desc[:-3].rstrip("#/.")
                segments = re.split(r"[/:]", base)
                short_name = segments[-1] + "()"
            else:
                segments = re.split(r"[/:]", display_name)
                short_name = segments[-1] if segments else display_name

            short_name = re.sub(r"\\.\\([a-zA-Z0-9_]+\\)$", "", short_name)"""

    new_target = """            display_name = clean_desc.rstrip("#/.")
            if clean_desc.endswith("()."):
                base = clean_desc[:-3].rstrip("#/.")
                segments = re.split(r"[/:#]", base)
                short_name = segments[-1] + "()"
            else:
                segments = re.split(r"[/:#]", display_name)
                short_name = segments[-1] if segments else display_name

            short_name = re.sub(r"\\.\\([a-zA-Z0-9_]+\\)$", "", short_name)
            if "#" in short_name:
                short_name = short_name.split("#")[-1]"""

    if old_target in content:
        content = content.replace(old_target, new_target)
        scip_parser_path.write_text(content, encoding="utf-8")
        print("[+] Updated method name parsing in scip_parser.py")
    else:
        print("[!] Warning: target block in scip_parser.py not found as exact match, checking alternative...")

    # Also check model.py
    model_path = ROOT_DIR / "src" / "graph_builder" / "domain" / "model.py"
    m_content = model_path.read_text(encoding="utf-8")
    old_m_target = """            self.add_node(
                GraphNode(
                    id=sid,
                    label=s["label"],"""

    new_m_target = """            node_label = s["label"]
            if (parent_cls_id or ntype in (NodeType.METHOD, NodeType.CONSTRUCTOR)) and "#" in node_label:
                node_label = node_label.split("#")[-1]

            self.add_node(
                GraphNode(
                    id=sid,
                    label=node_label,"""

    if old_m_target in m_content:
        m_content = m_content.replace(old_m_target, new_m_target)
        model_path.write_text(m_content, encoding="utf-8")
        print("[+] Updated node label in domain/model.py")


def update_scripts_file():
    up_path = ROOT_DIR / "scripts" / "update_graph_builder.py"
    if up_path.exists():
        content = up_path.read_text(encoding="utf-8")
        content = content.replace('"graph_builder/', '"src/graph_builder/')
        up_path.write_text(content, encoding="utf-8")
        print("[+] Updated paths in scripts/update_graph_builder.py")


def main():
    run_git_mv()
    update_cli_py()
    create_command_graph_py()
    update_build_graph_py()
    update_method_names()
    update_scripts_file()
    print("[+] Migration completed successfully!")


if __name__ == "__main__":
    main()
