"""Unit and topological invariance tests for parameter-free hierarchical clustering."""
import random
from pathlib import Path
import pytest

from db.connection import DbConnection
from db.repository import Repository
from clustering.analyzer import build_cluster_hierarchy
from interface.tools.clusters import handle_clusters
from interface.validators import validate_cluster_view, validate_cluster_unit


def _create_test_db(tmp_path: Path, files, symbols, edges):
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
                "INSERT INTO symbols (symbol, clean_symbol, filepath, kind, parent_symbol) VALUES (?, ?, ?, ?, ?)",
                [
                    sym["symbol"],
                    sym.get("clean_symbol", sym["symbol"]),
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


def test_shared_hub_lca_placement(tmp_path):
    """
    Invariant 1: Shared Hub LCA Placement.
    Three cliques A, B, C each calling a shared symbol Hub equally (3 edges each)
    => at Level 1 Hub is ejected into a 1-symbol cluster;
    at Level 2 (when A, B, C merge into ABC) Hub attaches directly under ABC.
    """
    files = [
        {"filepath": "lib/features/fa/a.dart"},
        {"filepath": "lib/features/fb/b.dart"},
        {"filepath": "lib/features/fc/c.dart"},
        {"filepath": "lib/shared/hub.dart"},
    ]
    symbols = [
        {"symbol": "a1", "filepath": "lib/features/fa/a.dart"},
        {"symbol": "a2", "filepath": "lib/features/fa/a.dart"},
        {"symbol": "a3", "filepath": "lib/features/fa/a.dart"},
        {"symbol": "b1", "filepath": "lib/features/fb/b.dart"},
        {"symbol": "b2", "filepath": "lib/features/fb/b.dart"},
        {"symbol": "b3", "filepath": "lib/features/fb/b.dart"},
        {"symbol": "c1", "filepath": "lib/features/fc/c.dart"},
        {"symbol": "c2", "filepath": "lib/features/fc/c.dart"},
        {"symbol": "c3", "filepath": "lib/features/fc/c.dart"},
        {"symbol": "Hub", "filepath": "lib/shared/hub.dart"},
    ]
    edges = [
        # Clique A
        {"source": "a1", "target": "a2"},
        {"source": "a2", "target": "a3"},
        {"source": "a3", "target": "a1"},
        # Clique B
        {"source": "b1", "target": "b2"},
        {"source": "b2", "target": "b3"},
        {"source": "b3", "target": "b1"},
        # Clique C
        {"source": "c1", "target": "c2"},
        {"source": "c2", "target": "c3"},
        {"source": "c3", "target": "c1"},
        # Calls to Hub (3 each)
        {"source": "a1", "target": "Hub"},
        {"source": "a2", "target": "Hub"},
        {"source": "a3", "target": "Hub"},
        {"source": "b1", "target": "Hub"},
        {"source": "b2", "target": "Hub"},
        {"source": "b3", "target": "Hub"},
        {"source": "c1", "target": "Hub"},
        {"source": "c2", "target": "Hub"},
        {"source": "c3", "target": "Hub"},
        # Inter-clique weak bridges so A, B, C merge into ABC at Level 2
        {"source": "a1", "target": "b1"},
        {"source": "b1", "target": "c1"},
        {"source": "c1", "target": "a1"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    # Hub should be a singleton cluster
    hub_cid = res.symbol_to_leaf["Hub"]
    hub_node = res.index_by_id[hub_cid]
    assert hub_node.is_singleton is True
    assert hub_node.symbol_ids == ("Hub",)

    # Its parent should be the enclosing subsystem containing A, B, C (its LCA)
    assert hub_node.parent_id is not None
    parent = res.index_by_id[hub_node.parent_id]
    # Parent should contain all A, B, C symbols as well
    assert set(parent.symbol_ids) >= {"a1", "b1", "c1", "Hub"}


def test_private_dependency_absorption(tmp_path):
    """
    Invariant 2: Private Dependency Absorption.
    Symbol Priv called exclusively by cluster A is absorbed into A
    (never reported as an external dependency of A).
    """
    files = [
        {"filepath": "lib/features/fa/a.dart"},
        {"filepath": "lib/shared/priv.dart"},
        {"filepath": "lib/features/fb/b.dart"},
    ]
    symbols = [
        {"symbol": "a1", "filepath": "lib/features/fa/a.dart"},
        {"symbol": "a2", "filepath": "lib/features/fa/a.dart"},
        {"symbol": "Priv", "filepath": "lib/shared/priv.dart"},
        {"symbol": "b1", "filepath": "lib/features/fb/b.dart"},
        {"symbol": "b2", "filepath": "lib/features/fb/b.dart"},
    ]
    edges = [
        {"source": "a1", "target": "a2"},
        {"source": "a2", "target": "a1"},
        {"source": "a1", "target": "Priv"},
        {"source": "a2", "target": "Priv"},
        {"source": "b1", "target": "b2"},
        {"source": "b2", "target": "b1"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    a1_cid = res.symbol_to_leaf["a1"]
    priv_cid = res.symbol_to_leaf["Priv"]

    # Priv should be absorbed into the same cluster or an immediate ancestor of A
    node_a = res.index_by_id[a1_cid]
    # Priv should not be an external dependency of node_a
    assert "Priv" not in node_a.ext_deps_by_cluster.get("external", [])
    # Either same leaf cluster or same direct cluster
    assert "Priv" in node_a.symbol_ids or a1_cid == priv_cid or node_a.parent_id == res.index_by_id[priv_cid].parent_id


def test_node_based_containment_accuracy(tmp_path):
    """
    Invariant 3: Node-Based Containment Accuracy.
    Cluster A with 9 internal symbols making 20 calls to 1 external symbol Hub
    reports ext_dep_count = 1 and containment_pct = 90.0% (9 / (9 + 1)).
    """
    files = [
        {"filepath": "lib/features/fa/a.dart"},
        {"filepath": "lib/shared/hub.dart"},
    ]
    symbols = [{"symbol": f"a{i}", "filepath": "lib/features/fa/a.dart"} for i in range(1, 10)]
    symbols.append({"symbol": "Hub", "filepath": "lib/shared/hub.dart"})

    edges = []
    # Make A cohesive (a chain and loop)
    for i in range(1, 9):
        edges.append({"source": f"a{i}", "target": f"a{i+1}"})
    edges.append({"source": "a9", "target": "a1"})

    # 9 calls from each of the 9 symbols in A to Hub
    for i in range(1, 10):
        edges.append({"source": f"a{i}", "target": "Hub", "weight": 2.22})

    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    a1_cid = res.symbol_to_leaf["a1"]
    node_a = res.index_by_id[a1_cid]

    # Cluster A contains 9 symbols, points to 1 external Hub
    assert len(node_a.symbol_ids) == 9
    assert node_a.ext_dep_count == 1
    # 9 / (9 + 1) * 100 = 90.0%
    assert node_a.containment_pct == 90.0


def test_mutual_cycle_atomicity(tmp_path):
    """
    Invariant 4: Mutual Cycle Atomicity.
    Mutually recursive symbols f <-> g remain inside the same Level-0 SCC (is_cycle=True).
    """
    files = [{"filepath": "lib/core/cycles.dart"}]
    symbols = [
        {"symbol": "fn_f", "clean_symbol": "fn_f", "filepath": "lib/core/cycles.dart"},
        {"symbol": "fn_g", "clean_symbol": "fn_g", "filepath": "lib/core/cycles.dart"},
    ]
    edges = [
        {"source": "fn_f", "target": "fn_g"},
        {"source": "fn_g", "target": "fn_f"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    f_cid = res.symbol_to_leaf["fn_f"]
    g_cid = res.symbol_to_leaf["fn_g"]
    assert f_cid == g_cid

    cycle_node = res.index_by_id[f_cid]
    assert cycle_node.is_cycle is True
    assert set(cycle_node.symbol_ids) == {"fn_f", "fn_g"}


def test_split_brain_class_detection(tmp_path):
    """
    Invariant 5: Split-Brain Class Detection.
    Class GodClass with 4 methods tightly coupled to Cluster A and 4 methods tightly coupled to Cluster B
    fractures cleanly under soft parent_symbol weighting and appears in drift.split_classes.
    """
    files = [
        {"filepath": "lib/features/fa/a.dart"},
        {"filepath": "lib/features/fb/b.dart"},
        {"filepath": "lib/core/god_class.dart"},
    ]
    symbols = [
        {"symbol": "GodClass", "filepath": "lib/core/god_class.dart", "kind": "Class"},
    ]
    for i in range(1, 5):
        symbols.append({"symbol": f"m_a{i}", "filepath": "lib/core/god_class.dart", "parent_symbol": "GodClass"})
        symbols.append({"symbol": f"a{i}", "filepath": "lib/features/fa/a.dart"})
    for i in range(1, 5):
        symbols.append({"symbol": f"m_b{i}", "filepath": "lib/core/god_class.dart", "parent_symbol": "GodClass"})
        symbols.append({"symbol": f"b{i}", "filepath": "lib/features/fb/b.dart"})

    edges = []
    # Cluster A tight coupling
    for i in range(1, 5):
        edges.append({"source": f"a{i}", "target": f"m_a{i}"})
        edges.append({"source": f"m_a{i}", "target": f"a{i}"})
    # Cluster B tight coupling
    for i in range(1, 5):
        edges.append({"source": f"b{i}", "target": f"m_b{i}"})
        edges.append({"source": f"m_b{i}", "target": f"b{i}"})

    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    # GodClass methods should split across clusters
    m_a1_cid = res.symbol_to_leaf["m_a1"]
    m_b1_cid = res.symbol_to_leaf["m_b1"]
    assert m_a1_cid != m_b1_cid

    # Must appear in drift.split_classes
    split_cls_names = [sc["class_symbol"] for sc in res.drift.split_classes]
    assert "GodClass" in split_cls_names


def test_misplaced_symbol_and_split_brain_file(tmp_path):
    """
    Invariant 6: Misplaced Symbol & Split-Brain File Detection.
    File a.dart containing 5 symbols from Cluster A and 1 symbol wired exclusively to Cluster B
    flags that outlier in drift.misplaced_symbols.
    """
    files = [
        {"filepath": "lib/features/fa/a.dart"},
        {"filepath": "lib/features/fb/b.dart"},
    ]
    symbols = [
        {"symbol": f"a{i}", "filepath": "lib/features/fa/a.dart"} for i in range(1, 6)
    ]
    # 1 outlier in a.dart wired to B
    symbols.append({"symbol": "outlier_b", "filepath": "lib/features/fa/a.dart"})
    symbols.extend([
        {"symbol": f"b{i}", "filepath": "lib/features/fb/b.dart"} for i in range(1, 5)
    ])

    edges = []
    # Cluster A internal
    for i in range(1, 5):
        edges.append({"source": f"a{i}", "target": f"a{i+1}"})
        edges.append({"source": f"a{i+1}", "target": f"a{i}"})
    # Cluster B internal
    for i in range(1, 4):
        edges.append({"source": f"b{i}", "target": f"b{i+1}"})
        edges.append({"source": f"b{i+1}", "target": f"b{i}"})
    # outlier_b wired tightly to B
    for i in range(1, 5):
        edges.append({"source": "outlier_b", "target": f"b{i}"})
        edges.append({"source": f"b{i}", "target": "outlier_b"})

    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    misplaced_syms = [m["symbol"] for m in res.drift.misplaced_symbols]
    assert "outlier_b" in misplaced_syms


def test_deterministic_stability(tmp_path):
    """
    Invariant 7: Deterministic Stability.
    Shuffling database insertion order produces identical cluster hierarchy, identical c1.2 IDs, and identical Mermaid output.
    """
    files = [
        {"filepath": "lib/fa/a.dart"},
        {"filepath": "lib/fb/b.dart"},
    ]
    symbols = [
        {"symbol": f"sym_a{i}", "filepath": "lib/fa/a.dart"} for i in range(1, 5)
    ] + [
        {"symbol": f"sym_b{i}", "filepath": "lib/fb/b.dart"} for i in range(1, 5)
    ]
    edges = [
        {"source": "sym_a1", "target": "sym_a2"},
        {"source": "sym_a2", "target": "sym_a3"},
        {"source": "sym_a3", "target": "sym_a4"},
        {"source": "sym_b1", "target": "sym_b2"},
        {"source": "sym_b2", "target": "sym_b3"},
        {"source": "sym_a1", "target": "sym_b1"},
    ]

    # Run 1: original order
    p1 = tmp_path / "run1"
    p1.mkdir()
    repo1 = _create_test_db(p1, files, symbols, edges)
    out1 = handle_clusters(repo1, p1, view="both")

    # Run 2: shuffled order
    p2 = tmp_path / "run2"
    p2.mkdir()
    shuffled_symbols = list(symbols)
    shuffled_edges = list(edges)
    random.seed(42)
    random.shuffle(shuffled_symbols)
    random.shuffle(shuffled_edges)
    repo2 = _create_test_db(p2, files, shuffled_symbols, shuffled_edges)
    out2 = handle_clusters(repo2, p2, view="both")

    assert out1 == out2


def test_scope_boundary_preservation(tmp_path):
    """
    Invariant 8: Scope Boundary Preservation.
    Passing scope="lib/features/graph" still counts calls targeting lib/shared/ or rust/
    inside ext_dep_count rather than falsely inflating containment to 100%.
    """
    files = [
        {"filepath": "lib/features/graph/store.dart"},
        {"filepath": "lib/shared/logger.dart"},
    ]
    symbols = [
        {"symbol": "Store.get", "filepath": "lib/features/graph/store.dart"},
        {"symbol": "Store.put", "filepath": "lib/features/graph/store.dart"},
        {"symbol": "Logger.log", "filepath": "lib/shared/logger.dart"},
    ]
    edges = [
        {"source": "Store.get", "target": "Store.put"},
        {"source": "Store.put", "target": "Logger.log"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path, scope="lib/features/graph")

    # Only Store.get and Store.put are active workspace symbols in scope
    assert len(res.root.symbol_ids) == 2
    store_cid = res.symbol_to_leaf["Store.get"]
    node_store = res.index_by_id[store_cid]

    # Logger.log is outside scope, but must be counted in ext_dep_count
    assert node_store.ext_dep_count >= 1
    assert node_store.containment_pct < 100.0


def test_validators_and_views(tmp_path):
    """Tests validator functions and view modes for handle_clusters."""
    ok, v = validate_cluster_view("tree")
    assert ok is True and v == "tree"
    ok, v = validate_cluster_view("INVALID")
    assert ok is False

    ok, u = validate_cluster_unit("file")
    assert ok is True and u == "file"
    ok, u = validate_cluster_unit("UNKNOWN")
    assert ok is False

    files = [{"filepath": "lib/a.dart"}]
    symbols = [
        {"symbol": "a1", "filepath": "lib/a.dart"},
        {"symbol": "a2", "filepath": "lib/a.dart"},
        {"symbol": "isolated_sym", "filepath": "lib/a.dart"},
    ]
    edges = [{"source": "a1", "target": "a2"}]
    repo = _create_test_db(tmp_path, files, symbols, edges)

    # Tree view
    tree_out = handle_clusters(repo, tmp_path, view="tree")
    assert "### Cluster Tree" in tree_out
    assert "```mermaid" not in tree_out

    # Mermaid view
    mermaid_out = handle_clusters(repo, tmp_path, view="mermaid")
    assert "Dependency Frontier (Mermaid)" in mermaid_out
    assert "### Cluster Tree" not in mermaid_out

    # Unreferenced inspection
    unref_out = handle_clusters(repo, tmp_path, cluster="unreferenced")
    assert "isolated_sym" in unref_out

    # File unit
    file_unit_out = handle_clusters(repo, tmp_path, unit="file")
    assert "unit=`file`" in file_unit_out


def test_mermaid_frontier_edges_between_non_leaf_clusters(tmp_path):
    """Verifies that Mermaid frontier edges are preserved at non-leaf depth (depth=1)."""
    files = [
        {"filepath": "lib/fa/a.dart"},
        {"filepath": "lib/fb/b.dart"},
    ]
    symbols = [
        {"symbol": "a1", "filepath": "lib/fa/a.dart"},
        {"symbol": "a2", "filepath": "lib/fa/a.dart"},
        {"symbol": "b1", "filepath": "lib/fb/b.dart"},
        {"symbol": "b2", "filepath": "lib/fb/b.dart"},
    ]
    edges = [
        {"source": "a1", "target": "a2"},
        {"source": "b1", "target": "b2"},
        {"source": "a1", "target": "b1"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    # depth=1 means frontier nodes are the top-level clusters (e.g. c1, c2)
    out = handle_clusters(repo, tmp_path, depth=1, view="mermaid")
    assert "-->|1|" in out


def test_filepath_zoom_resolves_to_finest_cluster(tmp_path):
    """Verifies that filepath zoom (with backslashes) resolves to finest enclosing cluster, not root."""
    files = [
        {"filepath": "lib/features/fa/a.dart"},
        {"filepath": "lib/features/fb/b.dart"},
    ]
    symbols = [
        {"symbol": "a1", "filepath": "lib/features/fa/a.dart"},
        {"symbol": "b1", "filepath": "lib/features/fb/b.dart"},
    ]
    edges = [{"source": "a1", "target": "b1"}]
    repo = _create_test_db(tmp_path, files, symbols, edges)

    # Windows backslash path
    out = handle_clusters(repo, tmp_path, cluster=r"lib\features\fa\a.dart")
    assert "Focus**: `root`" not in out
    assert "Cluster Details: `[" in out or "a1" in out


def test_dead_code_called_only_by_tests_remains_unreferenced(tmp_path):
    """Verifies that when include_tests=False, production symbols called only by tests stay unreferenced."""
    files = [
        {"filepath": "lib/prod/util.dart"},
        {"filepath": "test/util_test.dart"},
    ]
    symbols = [
        {"symbol": "dead_func", "filepath": "lib/prod/util.dart"},
        {"symbol": "test_func", "filepath": "test/util_test.dart"},
    ]
    edges = [
        {"source": "test_func", "target": "dead_func"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path, include_tests=False)

    unref_names = [u["symbol"] for u in res.unreferenced_symbols]
    assert "dead_func" in unref_names


def test_comma_separated_scope_string(tmp_path):
    """Verifies that comma-separated scope string parses and filters correctly."""
    files = [
        {"filepath": "lib/fa/a.dart"},
        {"filepath": "lib/fb/b.dart"},
        {"filepath": "lib/other/c.dart"},
    ]
    symbols = [
        {"symbol": "a1", "filepath": "lib/fa/a.dart"},
        {"symbol": "b1", "filepath": "lib/fb/b.dart"},
        {"symbol": "c1", "filepath": "lib/other/c.dart"},
    ]
    edges = [
        {"source": "a1", "target": "b1"},
        {"source": "b1", "target": "c1"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path, scope="lib/fa, lib/fb")

    # Only a1 and b1 should be in the active scope
    assert set(res.root.symbol_ids) == {"a1", "b1"}
    assert "c1" not in res.root.symbol_ids


def test_implements_does_not_fuse_interface_and_impl_into_tarjan_cycle(tmp_path):
    """Verifies that Interface and Concrete implementation do not form an atomic Level-0 cycle."""
    files = [
        {"filepath": "lib/iface.dart"},
        {"filepath": "lib/impl.dart"},
    ]
    symbols = [
        {"symbol": "MyInterface", "clean_symbol": "MyInterface", "filepath": "lib/iface.dart", "kind": "Interface"},
        {"symbol": "MyImpl", "clean_symbol": "MyImpl", "filepath": "lib/impl.dart", "kind": "Class"},
    ]
    edges = [
        {"source": "MyImpl", "target": "MyInterface", "relation": "Implements"},
        {"source": "MyImpl", "target": "MyInterface", "relation": "Calls"},
    ]
    repo = _create_test_db(tmp_path, files, symbols, edges)
    res = build_cluster_hierarchy(repo, tmp_path)

    # They must NOT be fused into an atomic Level-0 Tarjan cycle
    impl_cid = res.symbol_to_leaf["MyImpl"]
    impl_node = res.index_by_id[impl_cid]
    assert impl_node.is_cycle is False

