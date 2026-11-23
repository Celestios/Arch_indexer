from engines.polymorphism import (
    POLYMORPHIC_KINDS,
    IMPLEMENTS_RELATION,
    VIRTUAL_DISPATCH_RELATION,
    is_polymorphic_kind,
    expand_virtual_neighbors,
    build_propagation_adjacency,
)


def test_is_polymorphic_kind():
    assert is_polymorphic_kind("Trait") is True
    assert is_polymorphic_kind("Interface") is True
    assert is_polymorphic_kind("AbstractMethod") is True
    assert is_polymorphic_kind("Protocol") is True
    assert is_polymorphic_kind("Class") is False
    assert is_polymorphic_kind("Method") is False
    assert is_polymorphic_kind(None) is False


def test_expand_virtual_neighbors():
    class MockGraph:
        def get_symbol(self, sym):
            if sym == "MyTrait":
                return {"kind": "Trait"}
            return {"kind": "Class"}

        def get_edges(self, source=None, target=None, relation=None):
            if source == "ImplA" and relation == "Implements":
                return [{"source": "ImplA", "target": "MyTrait", "relation": "Implements", "weight": 1.0}]
            if target == "MyTrait" and relation == "Implements":
                return [{"source": "ImplA", "target": "MyTrait", "relation": "Implements", "weight": 1.0}]
            return []

    class MockRepo:
        graph = MockGraph()

    repo = MockRepo()

    # Upstream: ImplA -> MyTrait (implements)
    up = expand_virtual_neighbors(repo, "ImplA", "upstream")
    assert len(up) == 1
    assert up[0] == ("MyTrait", 0.6, "VirtualDispatch")

    # Downstream: MyTrait -> ImplA (runtime dispatch)
    down = expand_virtual_neighbors(repo, "MyTrait", "downstream")
    assert len(down) == 1
    assert down[0] == ("ImplA", 0.6, "VirtualDispatch")


def test_build_propagation_adjacency():
    edges = [
        {"source": "Service", "target": "RepositoryTrait", "relation": "Calls"},
        {"source": "SqlRepository", "target": "RepositoryTrait", "relation": "Implements"},
    ]
    sym_classes = {
        "Service": {"symbol_info": {"kind": "Class"}},
        "RepositoryTrait": {"symbol_info": {"kind": "Trait"}},
        "SqlRepository": {"symbol_info": {"kind": "Class"}},
    }

    adj_fwd, adj_back = build_propagation_adjacency(edges, sym_classes)

    # Standard call: Service -> RepositoryTrait
    assert "RepositoryTrait" in adj_fwd["Service"]
    assert "Service" in adj_back["RepositoryTrait"]

    # Implements edge: runtime dispatch flows RepositoryTrait -> SqlRepository
    assert "SqlRepository" in adj_fwd["RepositoryTrait"]
    assert "RepositoryTrait" in adj_back["SqlRepository"]
