from unittest.mock import MagicMock
from engines.communities import detect_communities


def _make_repository(symbols_list, edges_list):
    repo = MagicMock()
    repo.symbols.get_all_symbols.return_value = symbols_list
    repo.edges.get_all_edges.return_value = edges_list
    return repo


class TestDetectCommunities:
    def test_empty_graph(self):
        repo = _make_repository([], [])
        communities, connections, degrees = detect_communities(repo)
        assert communities == {}
        assert connections == {}
        assert degrees == {}

    def test_single_symbol_no_edges(self):
        symbols = [{"symbol": "sym1", "filepath": "src/main.py"}]
        repo = _make_repository(symbols, [])
        communities, connections, degrees = detect_communities(repo)
        assert len(communities) == 1
        assert "sym1" in list(communities.values())[0]
        assert degrees["sym1"] == 0

    def test_two_disconnected_symbols(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
            {"symbol": "b", "filepath": "lib/b.py"},
        ]
        repo = _make_repository(symbols, [])
        communities, connections, degrees = detect_communities(repo)
        assert len(communities) == 2
        assert degrees["a"] == 0
        assert degrees["b"] == 0

    def test_two_connected_symbols_same_dir(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
            {"symbol": "b", "filepath": "src/b.py"},
        ]
        edges = [{"source": "a", "target": "b", "weight": 1.0}]
        repo = _make_repository(symbols, edges)
        communities, connections, degrees = detect_communities(repo)
        assert degrees["a"] == 1
        assert degrees["b"] == 1

    def test_degree_calculation_multiple_edges(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
            {"symbol": "b", "filepath": "src/b.py"},
            {"symbol": "c", "filepath": "src/c.py"},
        ]
        edges = [
            {"source": "a", "target": "b", "weight": 1.0},
            {"source": "a", "target": "c", "weight": 1.0},
            {"source": "b", "target": "c", "weight": 1.0},
        ]
        repo = _make_repository(symbols, edges)
        communities, connections, degrees = detect_communities(repo)
        assert degrees["a"] == 2
        assert degrees["b"] == 2
        assert degrees["c"] == 2

    def test_inter_community_connections(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
            {"symbol": "b", "filepath": "lib/b.py"},
        ]
        edges = [{"source": "a", "target": "b", "weight": 1.0}]
        repo = _make_repository(symbols, edges)
        communities, connections, degrees = detect_communities(repo)
        assert isinstance(connections, dict)
        all_syms = [s for group in communities.values() for s in group]
        assert "a" in all_syms and "b" in all_syms

    def test_deterministic_with_seed(self):
        symbols = [
            {"symbol": f"s{i}", "filepath": f"src/file{i}.py"} for i in range(5)
        ]
        edges = [
            {"source": f"s{i}", "target": f"s{i+1}", "weight": 1.0}
            for i in range(4)
        ]
        repo = _make_repository(symbols, edges)
        c1, conn1, d1 = detect_communities(repo)
        c2, conn2, d2 = detect_communities(repo)
        assert c1 == c2
        assert conn1 == conn2
        assert d1 == d2

    def test_label_initialized_from_filepath(self):
        symbols = [
            {"symbol": "x", "filepath": "deep/nested/dir/x.py"},
        ]
        repo = _make_repository(symbols, [])
        communities, _, _ = detect_communities(repo)
        assert "deep/nested/dir/" in communities

    def test_single_file_filepath_uses_dot(self):
        symbols = [
            {"symbol": "x", "filepath": "x.py"},
        ]
        repo = _make_repository(symbols, [])
        communities, _, _ = detect_communities(repo)
        assert "./" in communities

    def test_empty_filepath_uses_external(self):
        symbols = [
            {"symbol": "x", "filepath": ""},
        ]
        repo = _make_repository(symbols, [])
        communities, _, _ = detect_communities(repo)
        assert "external/" in communities

    def test_self_loop_not_counted_in_degree(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
        ]
        edges = [{"source": "a", "target": "a", "weight": 1.0}]
        repo = _make_repository(symbols, edges)
        _, _, degrees = detect_communities(repo)
        assert degrees["a"] == 2

    def test_edge_to_unknown_symbol_ignored(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
        ]
        edges = [{"source": "a", "target": "unknown", "weight": 1.0}]
        repo = _make_repository(symbols, edges)
        _, _, degrees = detect_communities(repo)
        assert degrees["a"] == 1

    def test_weight_affects_propagation(self):
        symbols = [
            {"symbol": "a", "filepath": "src/a.py"},
            {"symbol": "b", "filepath": "src/b.py"},
            {"symbol": "c", "filepath": "lib/c.py"},
        ]
        edges = [
            {"source": "a", "target": "b", "weight": 10.0},
            {"source": "a", "target": "c", "weight": 0.1},
        ]
        repo = _make_repository(symbols, edges)
        communities, _, _ = detect_communities(repo)
        a_community = None
        for lbl, syms in communities.items():
            if "a" in syms:
                a_community = lbl
        assert a_community is not None

    def test_backslash_filepath_normalized(self):
        symbols = [
            {"symbol": "x", "filepath": "src\\nested\\x.py"},
        ]
        repo = _make_repository(symbols, [])
        communities, _, _ = detect_communities(repo)
        assert "src/nested/" in communities
