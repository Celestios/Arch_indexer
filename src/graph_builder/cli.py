"""
Core Runner for the Modular Electronic Circuit Board HTML Graph Builder.
"""

import os
import webbrowser
from typing import Optional, Union, List, Set
from pathlib import Path

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
    exclude_boilerplate: bool = True,
    scope: Optional[Union[str, List[str], Set[str]]] = None,
    config_path: Optional[str] = None,
    open_browser: bool = False,
    project_root: Optional[Union[str, Path]] = None,
) -> str:
    cfg = CircuitConfig.load(config_path)
    effective_max_refs = max_refs_per_symbol if max_refs_per_symbol is not None else cfg.max_refs_per_symbol

    if project_root is None:
        p_db = Path(db_path).resolve()
        if p_db.parent.name == ".arch":
            project_root = p_db.parent.parent

    print(f"[*] Connecting to database: {db_path}")
    reader = DatabaseReader(db_path=db_path)
    stats = reader.get_summary_stats()
    print(
        f"[*] Workspace totals: {stats['files_count']} files, {stats['symbols_count']} symbols, "
        f"{stats['occurrences_count']} occurrences, {stats['edges_count']} edges"
    )

    scope_desc = ",".join(scope) if isinstance(scope, (list, set, tuple)) else (scope or "all")
    print(f"[*] Building knowledge graph model (scope: {scope_desc}, exclude_tests: {exclude_tests}, exclude_boilerplate: {exclude_boilerplate})...")
    model = GraphModel(
        include_occurrences=include_occurrences,
        max_refs_per_symbol=effective_max_refs,
        include_external=include_external,
        exclude_tests=exclude_tests,
        exclude_parameters=exclude_parameters,
        exclude_boilerplate=exclude_boilerplate,
        scope=scope,
        hub_threshold=cfg.hub_threshold,
        project_root=project_root,
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
