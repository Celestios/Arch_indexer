"""
Unit tests for the upgraded graph_builder modules:
- db_reader.py (Signature port extraction, edge call-site coordinates)
- graph_model.py (Eliminate file nodes/contains edges, aggregate occurrences, tag hubs, order calls)
- circuit_layout.py (Pure file packages, nested classes, directional pins, channel A* router, compact serialization)
- html_generator.py (HTML canvas visualizer generation)
"""

import os
import pytest
from graph_builder.ingestion.db_reader import DatabaseReader
from graph_builder.domain.model import GraphModel, NodeType, EdgeType, GraphNode, GraphEdge
from graph_builder.layout.circuit_layout import CircuitLayoutEngine
from graph_builder.serialization.compressor import compress_circuit_data
from graph_builder.renderer.html_generator import HtmlGraphGenerator


def test_signature_port_parsing():
    # 1. Standard python signature in markdown docstring (self/cls are omitted as implicit receivers)
    doc1 = """```python
def run_analysis(
  self,
  rules: List[Rule],
  config: Dict[str, Any] = {}
) -> AnalysisResult:
```
Analyzes code against rules."""
    ports1 = DatabaseReader.parse_signature_ports(docstring=doc1)
    assert len(ports1["inputs"]) == 2
    assert ports1["inputs"][0]["name"] == "rules"
    assert ports1["inputs"][0]["type"] == "List[Rule]"
    assert ports1["inputs"][1]["name"] == "config"
    assert ports1["inputs"][1]["type"] == "Dict[str, Any]"
    assert ports1["output"] == "AnalysisResult"

    # 2. Simple signature without return type
    doc2 = "```python\ndef helper(x: int, y: str):\n```"
    ports2 = DatabaseReader.parse_signature_ports(docstring=doc2)
    assert len(ports2["inputs"]) == 2
    assert ports2["inputs"][0] == {"name": "x", "type": "int"}
    assert ports2["inputs"][1] == {"name": "y", "type": "str"}
    assert ports2["output"] is None

    # 3. Direct signature string
    sig3 = "(data: bytes, timeout: float = 5.0) -> bool"
    ports3 = DatabaseReader.parse_signature_ports(signature_str=sig3)
    assert len(ports3["inputs"]) == 2
    assert ports3["inputs"][0] == {"name": "data", "type": "bytes"}
    assert ports3["inputs"][1] == {"name": "timeout", "type": "float"}
    assert ports3["output"] == "bool"


def test_graph_model_elimination_of_file_nodes_and_contains_edges():
    model = GraphModel(scope="src")
    # Simulate nodes and packages
    node1 = GraphNode(
        id="sym:foo",
        label="foo()",
        type=NodeType.FUNCTION,
        color="#06b6d4",
        val=7,
        group="src/a.py",
        filepath="src/a.py",
    )
    model.add_node(node1)
    model.packages["src/a.py"] = {
        "id": "src/a.py",
        "filepath": "src/a.py",
        "filename": "a.py",
        "language": "python",
        "status": "COMPLIANT",
    }

    d = model.to_dict()
    assert len(d["nodes"]) == 1
    assert d["nodes"][0]["type"] == NodeType.FUNCTION.value
    # No FILE nodes
    assert all(n["type"] != NodeType.FILE.value for n in d["nodes"])
    # No CONTAINS edges
    assert all(e["type"] != EdgeType.CONTAINS.value for e in d["links"])
    # File metadata stored directly in packages
    assert len(d["packages"]) == 1
    assert d["packages"][0]["filepath"] == "src/a.py"
    assert d["packages"][0]["language"] == "python"


def test_graph_model_aggregate_repeated_occurrences_and_order_calls():
    model = GraphModel(scope="src")
    node_src = GraphNode(
        id="sym:caller",
        label="caller()",
        type=NodeType.FUNCTION,
        color="#06b6d4",
        val=7,
        group="src/a.py",
        filepath="src/a.py",
    )
    node_tgt = GraphNode(
        id="sym:callee",
        label="callee()",
        type=NodeType.FUNCTION,
        color="#06b6d4",
        val=7,
        group="src/b.py",
        filepath="src/b.py",
    )
    model.add_node(node_src)
    model.add_node(node_tgt)

    # Add repeated calls with different line/col coordinates
    model.add_edge("sym:caller", "sym:callee", EdgeType.CALLS, "Calls", call_site=(25, 4))
    model.add_edge("sym:caller", "sym:callee", EdgeType.CALLS, "Calls", call_site=(10, 8))
    model.add_edge("sym:caller", "sym:callee", EdgeType.CALLS, "Calls", call_site=(25, 4)) # Duplicate coordinate

    assert len(model.edges) == 1
    edge = model.edges[0]
    assert edge.call_count == 3
    assert len(edge.call_sites) == 2
    assert (25, 4) in edge.call_sites
    assert (10, 8) in edge.call_sites


def test_tag_high_fan_in_hubs():
    model = GraphModel(scope="src")
    hub_tgt = GraphNode(
        id="sym:hub",
        label="GlobalHub#",
        type=NodeType.CLASS,
        color="#a855f7",
        val=10,
        group="src/hub.py",
        filepath="src/hub.py",
    )
    model.add_node(hub_tgt)

    # Add 7 callers to exceed threshold of 6
    for i in range(7):
        caller = GraphNode(
            id=f"sym:caller_{i}",
            label=f"caller_{i}()",
            type=NodeType.FUNCTION,
            color="#06b6d4",
            val=7,
            group=f"src/c_{i}.py",
            filepath=f"src/c_{i}.py",
        )
        model.add_node(caller)
        model.add_edge(caller.id, hub_tgt.id, EdgeType.CALLS, "Calls")

    # Trigger hub tagging
    FAN_IN_THRESHOLD = 6
    for n in model.nodes.values():
        if n.in_degree > FAN_IN_THRESHOLD:
            n.is_hub = True

    for edge in model.edges:
        if edge.target == hub_tgt.id and model.nodes[edge.target].is_hub:
            edge.is_hub_stub = True
            edge.hub_stub_target = hub_tgt.label

    assert hub_tgt.is_hub is True
    assert all(e.is_hub_stub is True for e in model.edges)
    assert all(e.hub_stub_target == "GlobalHub#" for e in model.edges)


def test_circuit_layout_and_channel_routing():
    model = GraphModel(scope="src")
    # File A
    model.packages["src/pkg_a.py"] = {
        "id": "src/pkg_a.py",
        "filepath": "src/pkg_a.py",
        "filename": "pkg_a.py",
        "language": "python",
        "status": "COMPLIANT",
    }
    # Class with Method
    cls_node = GraphNode(
        id="sym:ClassA#",
        label="ClassA",
        type=NodeType.CLASS,
        color="#a855f7",
        val=10,
        group="src/pkg_a.py",
        filepath="src/pkg_a.py",
    )
    method_node = GraphNode(
        id="sym:ClassA#method_a().",
        label="method_a()",
        type=NodeType.METHOD,
        color="#10b981",
        val=7,
        group="src/pkg_a.py",
        filepath="src/pkg_a.py",
        parent_class="sym:ClassA#",
        ports={"inputs": [{"name": "self", "type": ""}, {"name": "x", "type": "int"}], "output": "bool"},
    )
    model.add_node(cls_node)
    model.add_node(method_node)

    # File B
    model.packages["src/pkg_b.py"] = {
        "id": "src/pkg_b.py",
        "filepath": "src/pkg_b.py",
        "filename": "pkg_b.py",
        "language": "python",
        "status": "COMPLIANT",
    }
    fn_b = GraphNode(
        id="sym:fn_b().",
        label="fn_b()",
        type=NodeType.FUNCTION,
        color="#06b6d4",
        val=7,
        group="src/pkg_b.py",
        filepath="src/pkg_b.py",
        ports={"inputs": [{"name": "val", "type": "str"}], "output": "None"},
    )
    model.add_node(fn_b)

    # Edge from method_a to fn_b
    model.add_edge(method_node.id, fn_b.id, EdgeType.CALLS, "Calls", call_site=(15, 8))

    graph_dict = model.to_dict()
    engine = CircuitLayoutEngine()
    layout_data = engine.apply_circuit_layout(graph_dict)

    # Verify pure container file packages with tab
    assert len(layout_data["packages"]) == 2
    pkg_a = next(p for p in layout_data["packages"] if p["filepath"] == "src/pkg_a.py")
    assert "tab_x" in pkg_a and "tab_y" in pkg_a and "tab_w" in pkg_a
    assert len(pkg_a["classes"]) == 1
    assert pkg_a["classes"][0]["id"] == cls_node.id

    # Verify pre-routed waypoints on edge
    assert len(layout_data["links"]) == 1
    edge = layout_data["links"][0]
    assert "waypoints" in edge
    wp = edge["waypoints"]
    assert len(wp) >= 4 # Coordinate array [x0, y0, x1, y1, ...]
    assert all(isinstance(coord, int) for coord in wp)

    # Test compact serialization
    compact = compress_circuit_data(layout_data)
    assert "strings" in compact
    assert "nodes" in compact
    assert "links" in compact
    assert "packages" in compact
    assert len(compact["links"][0][5]) >= 4 # Pre-routed waypoints


def test_html_generator():
    model = GraphModel(scope="src")
    model.packages["src/sample.py"] = {
        "id": "src/sample.py",
        "filepath": "src/sample.py",
        "filename": "sample.py",
    }
    node = GraphNode(
        id="sym:sample()",
        label="sample()",
        type=NodeType.FUNCTION,
        color="#06b6d4",
        val=7,
        group="src/sample.py",
        filepath="src/sample.py",
    )
    model.add_node(node)
    graph_dict = model.to_dict()

    engine = CircuitLayoutEngine()
    circuit_data = engine.apply_circuit_layout(graph_dict)
    compact_data = compress_circuit_data(circuit_data)

    gen = HtmlGraphGenerator()
    html = gen.generate_html(compact_data, title="Test Board")

    assert "<!DOCTYPE html>" in html
    assert "circuit-canvas" in html
    assert "btn-view-code" in html
    assert "code-viewer-modal" in html
    assert "code-gutter" in html
    assert "code-text" in html
    assert "drawTracesBatched" in html
    assert "drawPackages" in html
    assert "drawActiveNet" in html
    assert "drawComponents" in html


def test_code_extractor_and_defining_blocks(tmp_path):
    from src.utils.code_extractor import CodeExtractor

    # Create dummy python file
    code_file = tmp_path / "sample_service.py"
    code_file.write_text(
        "import os\n\n"
        "@dataclass\n"
        "class SampleService:\n"
        "    name: str\n\n"
        "    def do_work(self, count: int) -> bool:\n"
        "        # process\n"
        "        return count > 0\n\n"
        "def top_level_fn(x):\n"
        "    return x * 2\n"
    )

    extractor = CodeExtractor(root_dir=str(tmp_path))
    
    # 1. Test class extraction
    cls_res = extractor.extract_code("sample_service.py", "SampleService", line=4)
    assert cls_res is not None
    start, end, text = cls_res
    assert start == 3  # includes @dataclass decorator
    assert end == 9
    assert "class SampleService:" in text
    assert "def do_work" in text

    # 2. Test method extraction
    m_res = extractor.extract_code("sample_service.py", "do_work()", line=7, parent_class="SampleService")
    assert m_res is not None
    m_s, m_e, m_text = m_res
    assert m_s == 7
    assert m_e == 9
    assert "def do_work" in m_text
    assert "return count > 0" in m_text

    # 3. Test function extraction
    fn_res = extractor.extract_code("sample_service.py", "top_level_fn()", line=11)
    assert fn_res is not None
    assert "def top_level_fn" in fn_res[2]


def test_compact_nodes_serialization_with_code():
    node = GraphNode(
        id="sym:foo",
        label="foo()",
        type=NodeType.FUNCTION,
        color="#06b6d4",
        val=7,
        group="src/a.py",
        filepath="src/a.py",
        line=10,
        end_line=25,
        code="def foo():\n    return 42\n",
    )
    circuit_data = {
        "nodes": [node.to_dict()],
        "links": [],
        "packages": [],
        "zone_banners": [],
    }
    compact = compress_circuit_data(circuit_data)
    assert len(compact["nodes"]) == 1
    compact_node = compact["nodes"][0]
    # Code index is field 15, end_line is field 16
    code_idx = compact_node[15]
    end_line = compact_node[16]
    assert code_idx >= 0
    assert compact["strings"][code_idx] == "def foo():\n    return 42\n"
    assert end_line == 25


def test_circuit_config_and_hierarchical_funnel():
    from graph_builder.config import CircuitConfig
    from graph_builder.layout.zone_classifier import TopologicalZoneClassifier

    cfg = CircuitConfig.load("circuit_config.json")
    assert cfg.grid_size == 8
    assert cfg.hub_threshold == 6
    assert cfg.layout.zone_grid_threshold == 2
    assert cfg.layout.zone_max_cols == 5
    assert cfg.layout.zone_target_aspect_ratio == 2.0
    assert cfg.layout.column_highway_w == 560
    assert cfg.routing.intra_col_highway_offset == 60
    assert cfg.routing.cross_col_highway_offset == 260

    # Test directory funnel extraction
    packages = {
        "src/a.py": {"id": "src/a.py", "filepath": "src/a.py", "filename": "a.py"},
        "src/sub/b.py": {"id": "src/sub/b.py", "filepath": "src/sub/b.py", "filename": "b.py"},
    }
    funnel = TopologicalZoneClassifier.build_directory_funnel(packages, [], [], scope="src")
    assert "zones" in funnel
    assert len(funnel["zones"]) >= 1
    # Check that root unreckoned zone exists for root files
    root_zone = next((z for z in funnel["zones"] if z.get("is_root_unckoned")), None)
    assert root_zone is not None
    assert root_zone["depth"] == 0


def test_method_name_strips_class_prefix():
    from graph_builder.ingestion.scip_parser import ScipParser

    # SCIP python method format
    raw_sym = "scip-python python Arch_indexer 0.1.0 `auditor.propagation`/MetadataPropagator#run_propagation()."
    parsed = ScipParser.parse_scip_symbol(raw_sym)
    assert parsed["label"] == "run_propagation()"

    # Constructor
    raw_init = "scip-python python Arch_indexer 0.1.0 `auditor.propagation`/MetadataPropagator#__init__()."
    parsed_init = ScipParser.parse_scip_symbol(raw_init)
    assert parsed_init["label"] == "__init__()"

    # Property / method without ()
    raw_prop = "scip-python python Arch_indexer 0.1.0 `auditor.propagation`/MetadataPropagator#is_active"
    parsed_prop = ScipParser.parse_scip_symbol(raw_prop)
    assert parsed_prop["label"] == "is_active"

    # Class itself retains its name
    raw_cls = "scip-python python Arch_indexer 0.1.0 `auditor.propagation`/MetadataPropagator#"
    parsed_cls = ScipParser.parse_scip_symbol(raw_cls)
    assert parsed_cls["label"] == "MetadataPropagator"


def test_graph_command_registration():
    import argparse
    from commands import register_all

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    register_all(subparsers)

    assert "graph" in subparsers.choices
    graph_parser = subparsers.choices["graph"]
    parsed = graph_parser.parse_args(["--output", "custom.html", "--scope", "src"])
    assert parsed.output == "custom.html"
    assert parsed.scope == "src"
    assert hasattr(parsed, "func")


def test_html_generator_safe_escaping_and_script_tags():
    """Verify that strings containing </script>, <!--, etc. do not break HTML or JavaScript."""
    gen = HtmlGraphGenerator()
    compact_data = {
        "strings": [
            "<script>alert('xss')</script>",
            "line1\r\nline2\nline3",
            "<!-- comment -->",
        ],
        "nodes": [],
        "links": [],
        "packages": [],
        "stats": {"total_nodes": 0, "total_edges": 0, "packages_count": 0},
    }
    html = gen.generate_html(compact_data, title="<Test & Safe>")
    # Title must be escaped
    assert "<title>&lt;Test &amp; Safe&gt;</title>" in html
    # Raw unescaped </script> must not appear inside the json data
    # Only one </script> should exist in the entire HTML (the actual closing tag)
    assert html.count("</script>") == 1
    assert "\\u003c/script\\u003e" in html



