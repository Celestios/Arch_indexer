import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from engines.scip.parser import ScipParser, _detect_scip_run_dir

def test_detect_scip_run_dir_from_metadata(tmp_path):
    project_root = tmp_path
    run_dir = tmp_path / "rust"
    run_dir.mkdir()
    
    # file URI pointing to real directory
    uri = run_dir.as_uri()
    
    res = _detect_scip_run_dir(tmp_path / "index_rust.scip", project_root, uri)
    assert res == run_dir

def test_detect_scip_run_dir_fallback(tmp_path):
    project_root = tmp_path
    run_dir = tmp_path / "rust"
    run_dir.mkdir()
    (run_dir / "Cargo.toml").write_text("[package]")
    
    res = _detect_scip_run_dir(tmp_path / "index_rust.scip", project_root, None)
    assert res == run_dir

@patch("engines.scip.parser.scip_pb2.Index")
@patch("engines.scip.parser.load_include_dirs")
@patch("engines.scip.parser.is_included")
def test_parse_index_path_normalization(mock_is_included, mock_load_include, mock_index_cls, tmp_path):
    project_root = tmp_path
    run_dir = tmp_path / "rust"
    run_dir.mkdir()
    
    # Setup mock index
    mock_index = MagicMock()
    mock_index.metadata.project_root = run_dir.as_uri()
    mock_index.external_symbols = []
    
    mock_doc = MagicMock()
    mock_doc.relative_path = "src/domain/contents.rs"
    
    mock_sym = MagicMock()
    mock_sym.symbol = "rust-analyzer cargo rust_lib_mycelium 0.3.0 crate/src/domain/contents.rs"
    mock_sym.documentation = ["docs"]
    mock_sym.kind = 1 # Struct
    mock_doc.symbols = [mock_sym]
    
    mock_occ = MagicMock()
    mock_occ.symbol = "rust-analyzer cargo rust_lib_mycelium 0.3.0 crate/src/domain/contents.rs"
    mock_occ.symbol_roles = 1 # Definition
    mock_occ.range = [3, 0, 3, 61]
    
    mock_occ_ref = MagicMock()
    mock_occ_ref.symbol = "rust-analyzer cargo rust_lib_mycelium 0.3.0 crate/src/domain/contents.rs"
    mock_occ_ref.symbol_roles = 0 # Reference
    mock_occ_ref.range = [5, 4, 5, 20]
    mock_doc.occurrences = [mock_occ, mock_occ_ref]
    
    mock_index.documents = [mock_doc]
    mock_index_cls.return_value = mock_index
    
    mock_load_include.return_value = {"rust"}
    mock_is_included.return_value = True
    
    # Run parse_index
    dummy_file = tmp_path / "index_rust.scip"
    dummy_file.write_bytes(b"dummy")
    
    parsed = ScipParser.parse_index(dummy_file, project_root=project_root)
    
    # Verify document path is resolved and normalized relative to project root
    assert "rust/src/domain/contents.rs" in parsed["files"]
    assert parsed["occurrences"][0]["filepath"] == "rust/src/domain/contents.rs"
    
    sym_key = "rust-analyzer cargo rust_lib_mycelium 0.3.0 crate/src/domain/contents.rs"
    assert sym_key in parsed["symbols"]
    assert parsed["symbols"][sym_key]["filepath"] == "rust/src/domain/contents.rs"
