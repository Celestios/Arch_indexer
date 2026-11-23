from pathlib import Path
from unittest.mock import MagicMock
import pytest

from engines.treesitter.loader import get_parser
from engines.treesitter.extractor import extract_symbols_from_file
from engines.registry import LanguageRegistry
from engines.scip.parser import parse_index
from db.connection import DbConnection
from db.repository import Repository
from interface.tools.map import handle_map


def test_dart_enum_extraction(tmp_path):
    dart_code = """
enum AppState {
  initial,
  loading,
  ready,
}
"""
    f = tmp_path / "app_state.dart"
    f.write_text(dart_code, encoding="utf-8")
    symbols = extract_symbols_from_file(f, project_root=tmp_path)
    assert any(s.name == "AppState" and s.kind == "Enum" for s in symbols)
    enum_sym = next(s for s in symbols if s.name == "AppState")
    assert enum_sym.start_line == 2
    assert enum_sym.end_line == 6


def test_tier1_decouples_ast_sha256_from_scip_sha256(tmp_path):
    db_file = tmp_path / "test.db"
    conn = DbConnection(db_file)
    repo = Repository(conn)

    # Simulate Tier 1 Tree-sitter sync
    repo.workspace.upsert_ast_file("lib/main.dart", "ast_hash_123", "dart")

    meta = repo.workspace.get_file("lib/main.dart")
    assert meta is not None
    assert meta["ast_sha256"] == "ast_hash_123"
    assert meta["sha256"] == ""  # SCIP hash is untouched

    # Simulate SCIP ingester checking changed files
    db_files = repo.workspace.get_all_files_metadata()
    current_disk_hash = "disk_hash_abc"
    db_hash = db_files.get("lib/main.dart", {}).get("sha256", "")
    assert current_disk_hash != db_hash  # Properly recognized as dirty!

    # SCIP ingestion marks the file
    repo.workspace.upsert_files([{"filepath": "lib/main.dart", "sha256": current_disk_hash, "language": "dart"}])
    meta_after = repo.workspace.get_file("lib/main.dart")
    assert meta_after["sha256"] == current_disk_hash


def test_delete_edges_preserves_injects_and_ffi_binds(tmp_path):
    db_file = tmp_path / "test.db"
    conn = DbConnection(db_file)
    repo = Repository(conn)

    with repo.transaction():
        repo.workspace.upsert_file("lib/ui.dart", "h1", "dart")
        repo.graph.upsert_syntactic_symbols([
            {"symbol": "sym_a", "clean_symbol": "sym_a", "filepath": "lib/ui.dart", "kind": "Class",
             "signature": "", "docstring": "", "body_hash": "b1", "connection_weight": 0, "parent_symbol": None,
             "start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0},
            {"symbol": "sym_b", "clean_symbol": "sym_b", "filepath": "lib/service.dart", "kind": "Class",
             "signature": "", "docstring": "", "body_hash": "b2", "connection_weight": 0, "parent_symbol": None,
             "start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0},
        ])
        repo.graph.upsert_edges([
            {"source": "sym_a", "target": "sym_b", "relation": "Injects", "weight": 0.9, "call_line": 5},
            {"source": "sym_a", "target": "sym_b", "relation": "FFI_Binds", "weight": 1.0, "call_line": 6},
            {"source": "sym_a", "target": "sym_b", "relation": "Calls", "weight": 1.0, "call_line": 7},
        ])

    # Delete edges for changed file lib/ui.dart, but exclude Injects and FFI_Binds
    repo.graph.delete_edges(filepaths=["lib/ui.dart"], exclude_relations=["Injects", "FFI_Binds"])

    remaining = repo.graph.get_edges()
    relations = {e["relation"] for e in remaining}
    assert "Injects" in relations
    assert "FFI_Binds" in relations
    assert "Calls" not in relations


def test_map_tool_handles_float_weights_and_no_zero_calls(tmp_path):
    db_file = tmp_path / "test.db"
    conn = DbConnection(db_file)
    repo = Repository(conn)

    with repo.transaction():
        repo.workspace.upsert_file("lib/features/graph/ui/widget.dart", "h1", "dart")
        repo.workspace.upsert_file("lib/features/graph/store/store.dart", "h2", "dart")
        repo.graph.upsert_syntactic_symbols([
            {"symbol": "ui_sym", "clean_symbol": "Widget", "filepath": "lib/features/graph/ui/widget.dart",
             "kind": "Class", "signature": "", "docstring": "", "body_hash": "b1", "connection_weight": 0,
             "parent_symbol": None, "start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0},
            {"symbol": "store_sym", "clean_symbol": "Store", "filepath": "lib/features/graph/store/store.dart",
             "kind": "Class", "signature": "", "docstring": "", "body_hash": "b2", "connection_weight": 0,
             "parent_symbol": None, "start_line": 1, "start_col": 0, "end_line": 10, "end_col": 0},
        ])
        # Edge with float weight 0.9 (e.g. Injects)
        repo.graph.upsert_edges([
            {"source": "ui_sym", "target": "store_sym", "relation": "Injects", "weight": 0.9, "call_line": 5}
        ])

    res = handle_map(repo, targets=[{"path": "lib/features/graph"}])
    assert "0 calls" not in res
    assert "1 call" in res


def test_vectorized_bulk_operations(tmp_path):
    db_file = tmp_path / "test.db"
    conn = DbConnection(db_file)
    repo = Repository(conn)

    with repo.transaction():
        # Test vectorized symbols
        symbols = [
            {"symbol": f"sym_{i}", "clean_symbol": f"Clean_{i}", "filepath": f"lib/file_{i%10}.dart",
             "kind": "Function", "signature": "void f()", "docstring": "", "body_hash": "h",
             "connection_weight": 0, "parent_symbol": None, "start_line": i, "start_col": 0,
             "end_line": i+1, "end_col": 10}
            for i in range(1000)
        ]
        repo.graph.upsert_syntactic_symbols(symbols)
        assert len(repo.graph.get_all_symbols()) == 1000

        # Test vectorized occurrences
        occs = [
            {"symbol": f"sym_{i}", "filepath": f"lib/file_{i%10}.dart",
             "start_line": i, "start_col": 0, "end_line": i, "end_col": 5, "role": 2}
            for i in range(1000)
        ]
        repo.graph.upsert_occurrences(occs)
        assert len(repo.graph.get_occurrences()) == 1000

        # Test vectorized edges
        edges = [
            {"source": f"sym_{i}", "target": f"sym_{(i+1)%1000}", "relation": "Calls",
             "weight": 1.0, "call_line": i}
            for i in range(1000)
        ]
        repo.graph.upsert_edges(edges)
        assert len(repo.graph.get_edges()) == 1000

        # Test vectorized edge weights update
        weight_updates = [(2.5, f"sym_{i}", f"sym_{(i+1)%1000}", "Calls") for i in range(1000)]
        repo.graph.update_edge_weights(weight_updates)
        edges_after = repo.graph.get_edges()
        assert all(e["weight"] == 2.5 for e in edges_after)

        # Test vectorized symbols classification update
        classifications = {f"sym_{i}": {"layer": "Domain", "index": i} for i in range(1000)}
        repo.graph.update_symbols_classification(classifications)
        sym_sample = repo.graph.get_symbol("sym_0")
        assert sym_sample is not None
        import json
        assert json.loads(sym_sample.get("classification")) == {"layer": "Domain", "index": 0}

