"""
CLI Runner for the Modular Electronic Circuit Board HTML Graph Builder.
Supports centralized JSON configuration via `--config`.
"""

import argparse
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


def main():
    parser = argparse.ArgumentParser(
        description="Build an electronic PCB circuit diagram HTML visualizer directly from DuckDB."
    )
    parser.add_argument("--db", default=".arch/arch.db", help="Path to DuckDB file")
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
    build_graph_html(
        db_path=args.db,
        output_path=args.output,
        include_occurrences=args.include_occurrences,
        max_refs_per_symbol=args.max_refs,
        include_external=args.include_external,
        exclude_tests=not args.include_tests,
        exclude_parameters=not args.include_parameters,
        scope=args.scope,
        config_path=args.config,
        open_browser=args.open,
    )


if __name__ == "__main__":
    main()
