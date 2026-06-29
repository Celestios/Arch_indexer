import json
from pathlib import Path
from engines.ffi_extractor import FfiExtractor, FfiSurface


def test_ffi_surface_dataclass():
    s = FfiSurface(symbol_name="native_init", signature="(i32) -> bool", filepath="src/lib.rs", language="rust")
    assert s.symbol_name == "native_init"
    assert s.signature == "(i32) -> bool"
    assert s.language == "rust"


def test_extract_rust_ffi_no_codeql(tmp_path):
    extractor = FfiExtractor(codeql_exe=None)
    results = extractor.extract_rust_ffi(tmp_path)
    assert results == []


def test_extract_dart_ffi_no_codeql(tmp_path):
    extractor = FfiExtractor(codeql_exe=None)
    results = extractor.extract_dart_ffi(tmp_path)
    assert results == []


def test_extract_all_returns_combined(tmp_path):
    extractor = FfiExtractor(codeql_exe=None)
    results = extractor.extract_all(tmp_path, languages=["rust", "dart"])
    assert results == []


def test_parse_rust_query_results():
    extractor = FfiExtractor(codeql_exe=None)
    tuples = [
        [{"type": "String", "value": "native_init"}, {"type": "String", "value": "fn(i32) -> bool"}, {"type": "String", "value": "src/lib.rs"}],
        [{"type": "String", "value": "process_data"}, {"type": "String", "value": "fn(&[u8]) -> i32"}, {"type": "String", "value": "src/ffi.rs"}],
    ]
    results = extractor._parse_query_results(tuples, "rust")
    assert len(results) == 2
    assert results[0].symbol_name == "native_init"
    assert results[0].signature == "fn(i32) -> bool"
    assert results[1].filepath == "src/ffi.rs"
