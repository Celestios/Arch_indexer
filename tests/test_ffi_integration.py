"""
Integration test for FFI cross-language linking.
Tests the full pipeline: extraction → matching → linking.
"""
from engines.ffi_extractor import FfiSurface
from engines.ffi_matcher import FfiMatcher
from engines.ffi_linker import FfiLinker
from setup.initializer import initialize_workspace, TEST_CONFIG_JSON
from db.connection import DbConnection
from db.repository import Repository
import json


def setup_workspace(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir(parents=True, exist_ok=True)
    with open(arch_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(TEST_CONFIG_JSON, f)
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def test_full_ffi_pipeline(tmp_path):
    """Simulates a Dart+Rust FFI project with multiple binding functions."""
    repository, db_conn, root = setup_workspace(tmp_path)

    # Simulate SCIP-indexed symbols
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('rust::src/lib.rs::native_init', 'src/lib.rs', 'Function', 'fn(i32) -> bool', 'Init', 'h1'),
                ('rust::src/lib.rs::process_data', 'src/lib.rs', 'Function', 'fn(&[u8]) -> i64', 'Process', 'h2'),
                ('rust::src/lib.rs::get_version', 'src/lib.rs', 'Function', 'fn() -> &str', 'Version', 'h3'),
                ('dart::lib/ffi.dart::native_init', 'lib/ffi.dart', 'Function', '(int) -> bool', 'Init', 'h4'),
                ('dart::lib/ffi.dart::process_data', 'lib/ffi.dart', 'Function', '(Uint8List) -> int', 'Process', 'h5')
        """)

    # Simulate CodeQL extraction results
    dart_surfaces = [
        FfiSurface("native_init", "(int) -> bool", "lib/ffi.dart", "dart"),
        FfiSurface("process_data", "(Uint8List) -> int", "lib/ffi.dart", "dart"),
    ]
    rust_surfaces = [
        FfiSurface("native_init", "fn(i32) -> bool", "src/lib.rs", "rust"),
        FfiSurface("process_data", "fn(&[u8]) -> i64", "src/lib.rs", "rust"),
        FfiSurface("get_version", "fn() -> &str", "src/lib.rs", "rust"),
    ]

    # Match
    matcher = FfiMatcher()
    matches = matcher.match(dart_surfaces, rust_surfaces)

    assert len(matches) == 2  # native_init + process_data matched, get_version unmatched

    # Link
    linker = FfiLinker(repository)
    edges_created = linker.link(matches)
    assert edges_created == 2

    # Verify in database
    with db_conn.session() as conn:
        ffi_edges = conn.execute(
            "SELECT source, target, relation, weight FROM edges WHERE relation = 'FFI_Binds' ORDER BY source"
        ).fetchall()
        assert len(ffi_edges) == 2
        assert ffi_edges[0][0] == "dart::lib/ffi.dart::native_init"
        assert ffi_edges[0][1] == "rust::src/lib.rs::native_init"

    # Verify transitive closure crosses FFI boundary
    closure = repository.edges.get_transitive_closure("dart::lib/ffi.dart::native_init", max_depth=3)
    downstream_symbols = [d["symbol"] for d in closure["downstream"]]
    assert "rust::src/lib.rs::native_init" in downstream_symbols

    db_conn.close()