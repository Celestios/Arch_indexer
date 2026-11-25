"""Verification tests for Instability (I), Macro Quotient Cycles, and Closure."""
from pathlib import Path
import pytest

from clustering.analyzer import build_cluster_hierarchy
from clustering.metrics import compute_metrics, populate_index_and_leaves
from clustering.models import ClusterHierarchyResult, ClusterNode, DriftReport
from db.connection import DbConnection
from db.repository import Repository
from interface.tools.clusters import _render_mermaid, handle_clusters


def _create_test_db(tmp_path: Path, files, symbols, edges) -> Repository:
    """Creates a temporary initialized DuckDB database populated with test fixtures."""
    db_file = tmp_path / "arch.db"
    conn = DbConnection(db_file)
    with conn.session() as s:
        for f in files:
            s.execute(
                "INSERT INTO files (filepath, sha256, language) VALUES (?, ?, ?)",
                [f["filepath"], f.get("sha256", "dummy_sha256"), f.get("language", "dart")],
            )
        for sym in symbols:
            s.execute(
                "INSERT INTO symbols (symbol, name, filepath, kind, parent_symbol) VALUES (?, ?, ?, ?, ?)",
                [
                    sym["symbol"],
                    sym.get("name", sym["symbol"]),
                    sym["filepath"],
                    sym.get("kind", "Function"),
                    sym.get("parent_symbol"),
                ],
            )
        for e in edges:
            s.execute(
                "INSERT INTO edges (source, target, relation) VALUES (?, ?, ?)",
                [e["source"], e["target"], e.get("relation", "Calls")],
            )
    return Repository(conn)


def _find_node_containing(root: ClusterNode, symbol_id: str) -> ClusterNode:
    """Finds the finest root-level child containing the given symbol."""
    for child in root.children:
        if symbol_id in child.symbol_ids:
            return child
    raise AssertionError(f"Symbol {symbol_id!r} not found in any root child")


def test_acyclic_shared_sink_refactor(tmp_path):
    """
    Acyclic shared-sink refactor:
    graph -> shared, text_editor -> shared yields:
    - internal_macro_cycles == 0
    - shared.instability == 0.0
    - graph.instability == 1.0
    - closure_ext_count == ext_dep_count
    """
    files = [
        {"filepath": "lib/features/graph/g.dart"},
        {"filepath": "lib/features/text_editor/t.dart"},
        {"filepath": "lib/features/canvas/c.dart"},
        {"filepath": "lib/shared/font.dart"},
    ]
    symbols = [
        {"symbol": "lib/features/graph/g.dart::GraphView", "name": "GraphView", "filepath": "lib/features/graph/g.dart"},
        {"symbol": "lib/features/graph/g.dart::GraphLayout", "name": "GraphLayout", "filepath": "lib/features/graph/g.dart"},
        {"symbol": "lib/features/text_editor/t.dart::EditorView", "name": "EditorView", "filepath": "lib/features/text_editor/t.dart"},
        {"symbol": "lib/features/text_editor/t.dart::EditorState", "name": "EditorState", "filepath": "lib/features/text_editor/t.dart"},
        {"symbol": "lib/features/canvas/c.dart::CanvasView", "name": "CanvasView", "filepath": "lib/features/canvas/c.dart"},
        {"symbol": "lib/features/canvas/c.dart::CanvasState", "name": "CanvasState", "filepath": "lib/features/canvas/c.dart"},
        {"symbol": "lib/shared/font.dart::FontRegistry", "name": "FontRegistry", "filepath": "lib/shared/font.dart"},
    ]
    edges = [
        {"source": "lib/features/graph/g.dart::GraphView", "target": "lib/features/graph/g.dart::GraphLayout"},
        {"source": "lib/features/graph/g.dart::GraphLayout", "target": "lib/features/graph/g.dart::GraphView"},
        {"source": "lib/features/graph/g.dart::GraphLayout", "target": "lib/shared/font.dart::FontRegistry"},
        {"source": "lib/features/text_editor/t.dart::EditorView", "target": "lib/features/text_editor/t.dart::EditorState"},
        {"source": "lib/features/text_editor/t.dart::EditorState", "target": "lib/features/text_editor/t.dart::EditorView"},
        {"source": "lib/features/text_editor/t.dart::EditorState", "target": "lib/shared/font.dart::FontRegistry"},
        {"source": "lib/features/canvas/c.dart::CanvasView", "target": "lib/features/canvas/c.dart::CanvasState"},
        {"source": "lib/features/canvas/c.dart::CanvasState", "target": "lib/features/canvas/c.dart::CanvasView"},
        {"source": "lib/features/canvas/c.dart::CanvasState", "target": "lib/shared/font.dart::FontRegistry"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path, unit="symbol")

    assert res.root.internal_macro_cycles == 0
    shared_node = _find_node_containing(res.root, "lib/shared/font.dart::FontRegistry")
    graph_node = _find_node_containing(res.root, "lib/features/graph/g.dart::GraphLayout")

    assert shared_node.instability == 0.0
    assert graph_node.instability == 1.0
    assert graph_node.closure_ext_count == graph_node.ext_dep_count
    assert graph_node.macro_cycle_peers == ()

    summary_out = handle_clusters(repo, tmp_path, view="summary")
    assert "0 (DAG)" in summary_out
    assert "Ext (Closure)" in summary_out


@pytest.mark.parametrize("unit", ["symbol", "file"])
def test_macro_cycle_without_symbol_scc(unit):
    """
    Macro cycle without symbol SCC:
    c1::a -> c2::b and c2::c -> c1::d yields:
    - is_cycle == False on leaves
    - root.internal_macro_cycles == 1
    - c1.macro_cycle_peers == ("c2",)
    - c1.cyclic_ext_dep_count == 1
    - ==>|1 cyclic| in Mermaid under both unit="symbol" and unit="file"
    """
    c1 = ClusterNode(
        cluster_id="c1",
        name="ModOne",
        level=0,
        parent_id="root",
        symbol_ids=("c1::a", "c1::d"),
        filepaths=("lib/c1/m1.dart",),
        is_cycle=False,
    )
    c2 = ClusterNode(
        cluster_id="c2",
        name="ModTwo",
        level=0,
        parent_id="root",
        symbol_ids=("c2::b", "c2::c"),
        filepaths=("lib/c2/m2.dart",),
        is_cycle=False,
    )
    root = ClusterNode(
        cluster_id="root",
        name="root",
        level=1,
        parent_id=None,
        children=[c1, c2],
        symbol_ids=("c1::a", "c1::d", "c2::b", "c2::c"),
        filepaths=("lib/c1/m1.dart", "lib/c2/m2.dart"),
    )

    active_symbols_map = {
        "c1::a": {"filepath": "lib/c1/m1.dart"},
        "c1::d": {"filepath": "lib/c1/m1.dart"},
        "c2::b": {"filepath": "lib/c2/m2.dart"},
        "c2::c": {"filepath": "lib/c2/m2.dart"},
    }
    dir_out_edges = {
        "c1::a": {"c2::b"},
        "c2::c": {"c1::d"},
    }
    dir_in_edges = {
        "c2::b": {"c1::a"},
        "c1::d": {"c2::c"},
    }
    index_by_id = {}
    symbol_to_leaf = {}
    populate_index_and_leaves(root, index_by_id, symbol_to_leaf)

    compute_metrics(
        node=root,
        unit=unit,
        active_symbols_map=active_symbols_map,
        dir_out_edges=dir_out_edges,
        dir_in_edges=dir_in_edges,
        external_targets_by_source={},
        external_callers_by_target={},
        symbol_to_leaf=symbol_to_leaf,
    )

    assert c1.is_cycle is False
    assert c2.is_cycle is False
    assert root.internal_macro_cycles == 1
    assert c1.macro_cycle_peers == ("c2",)
    assert c2.macro_cycle_peers == ("c1",)
    assert c1.cyclic_ext_dep_count == 1
    assert c2.cyclic_ext_dep_count == 1

    res = ClusterHierarchyResult(
        root=root,
        index_by_id=index_by_id,
        symbol_to_leaf=symbol_to_leaf,
        unreferenced_symbols=[],
        drift=DriftReport(split_files=[], split_classes=[], misplaced_symbols=[]),
        total_symbols=4,
        total_files=2,
        total_edges=2,
    )
    mermaid = "\n".join(_render_mermaid([c1, c2], unit=unit, result=res))
    assert "==>|1 cyclic|" in mermaid


def test_dip_symmetry_check(tmp_path):
    """
    DIP symmetry check:
    A -> I <- B (with B --[Implements]--> I) yields:
    - internal_macro_cycles == 0
    - I.instability == 0.0
    """
    files = [
        {"filepath": "lib/a.dart"},
        {"filepath": "lib/i.dart"},
        {"filepath": "lib/b.dart"},
    ]
    symbols = [
        {"symbol": "lib/a.dart::A", "name": "A", "filepath": "lib/a.dart", "kind": "Class"},
        {"symbol": "lib/i.dart::I", "name": "I", "filepath": "lib/i.dart", "kind": "Interface"},
        {"symbol": "lib/b.dart::B", "name": "B", "filepath": "lib/b.dart", "kind": "Class"},
    ]
    edges = [
        {"source": "lib/a.dart::A", "target": "lib/i.dart::I", "relation": "Calls"},
        {"source": "lib/b.dart::B", "target": "lib/i.dart::I", "relation": "Implements"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path, unit="symbol")

    assert res.root.internal_macro_cycles == 0
    i_node = _find_node_containing(res.root, "lib/i.dart::I")
    assert i_node.instability == 0.0
