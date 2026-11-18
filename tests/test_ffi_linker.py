import json
from pathlib import Path
from setup.initializer import initialize_workspace, DEFAULT_CONFIG_JSON
from db.connection import DbConnection
from db.repository import Repository
from engines.ffi_linker import FfiLinker, FfiMatch
import pytest


def setup_workspace(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir(parents=True, exist_ok=True)
    with open(arch_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG_JSON, f)
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def test_linker_creates_ffi_edges(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('rust::src/lib.rs::native_init', 'src/lib.rs', 'Function', 'fn(i32) -> bool', 'Rust init', 'h1'),
                ('dart::lib/ffi.dart::native_init', 'lib/ffi.dart', 'Function', '(int) -> bool', 'Dart init', 'h2')
        """)

    matches = [
        FfiMatch(
            source_symbol="dart::lib/ffi.dart::native_init",
            target_symbol="rust::src/lib.rs::native_init",
            confidence=0.8,
            match_type="name"
        )
    ]

    linker = FfiLinker(repository)
    edges_created = linker.link(matches)

    assert edges_created == 1

    with db_conn.session() as conn:
        res = conn.execute(
            "SELECT source, target, relation, weight FROM edges WHERE relation = 'FFI_Binds'"
        ).fetchall()
        assert len(res) == 1
        assert res[0][0] == "dart::lib/ffi.dart::native_init"
        assert res[0][1] == "rust::src/lib.rs::native_init"
        assert res[0][2] == "FFI_Binds"
        assert res[0][3] == pytest.approx(0.8)

    db_conn.close()


def test_linker_skips_missing_symbols(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    matches = [
        FfiMatch(
            source_symbol="dart::lib/ffi.dart::missing_fn",
            target_symbol="rust::src/lib.rs::missing_fn",
            confidence=0.8,
            match_type="name"
        )
    ]

    linker = FfiLinker(repository)
    edges_created = linker.link(matches)
    assert edges_created == 0

    db_conn.close()


def test_linker_clears_old_ffi_edges_before_relink(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('rust::src/lib.rs::native_init', 'src/lib.rs', 'Function', 'fn(i32) -> bool', 'Rust init', 'h1'),
                ('dart::lib/ffi.dart::native_init', 'lib/ffi.dart', 'Function', '(int) -> bool', 'Dart init', 'h2')
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation, weight)
            VALUES ('dart::lib/ffi.dart::native_init', 'rust::src/lib.rs::native_init', 'FFI_Binds', 0.5)
        """)

    with db_conn.session() as conn:
        res = conn.execute("SELECT weight FROM edges WHERE relation = 'FFI_Binds'").fetchall()
        assert len(res) == 1
        assert res[0][0] == 0.5

    matches = [
        FfiMatch(
            source_symbol="dart::lib/ffi.dart::native_init",
            target_symbol="rust::src/lib.rs::native_init",
            confidence=1.0,
            match_type="name+signature"
        )
    ]

    linker = FfiLinker(repository)
    edges_created = linker.link(matches)

    with db_conn.session() as conn:
        res = conn.execute("SELECT weight FROM edges WHERE relation = 'FFI_Binds'").fetchall()
        assert len(res) == 1
        assert res[0][0] == 1.0

    db_conn.close()


def test_link_scip_bridges_direct(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('dart_app_handle_add_spring', 'lib.bridge.api.dart.AppHandle.addAnchorSpring()', 'lib/bridge/api.dart', 'Method', 'void addAnchorSpring()', '', 'h1'),
                ('rust_app_handle_add_spring', 'centrode_core.bridge.api.impl.[AppHandle]add_anchor_spring()', 'native/bridge/api.rs', 'Method', 'pub fn add_anchor_spring(&self)', '', 'h2'),
                ('dart_init_engine', 'lib.bridge.api.dart.initCoreEngine()', 'lib/bridge/api.dart', 'Function', 'void initCoreEngine()', '', 'h3'),
                ('rust_init_engine', 'centrode_core.bridge.api.init_core_engine()', 'native/bridge/api.rs', 'Function', 'pub fn init_core_engine()', '', 'h4'),
                ('dart_app_handle_new', 'lib.bridge.api.dart.AppHandle.newInstance()', 'lib/bridge/api.dart', 'Constructor', 'AppHandle.newInstance()', '', 'h5'),
                ('rust_app_handle_new', 'centrode_core.bridge.api.impl.[AppHandle]new()', 'native/bridge/api.rs', 'Constructor', 'pub fn new()', '', 'h6')
        """)

    linker = FfiLinker(repository)
    edges_created = linker.link_scip_bridges()

    assert edges_created == 3

    with db_conn.session() as conn:
        res = conn.execute(
            "SELECT source, target, relation FROM edges WHERE relation = 'FFI_Binds' ORDER BY source"
        ).fetchall()
        assert len(res) == 3
        sources = [r[0] for r in res]
        targets = [r[1] for r in res]
        assert "dart_app_handle_add_spring" in sources
        assert "rust_app_handle_add_spring" in targets
        assert "dart_init_engine" in sources
        assert "rust_init_engine" in targets
        assert "dart_app_handle_new" in sources
        assert "rust_app_handle_new" in targets

    db_conn.close()


def test_link_scip_bridges_excludes_boilerplate(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('dart_gen_sym', 'lib.bridge.api.freezed.AppHandle.addAnchorSpring()', 'lib/bridge/api.freezed.dart', 'Method', 'void addAnchorSpring()', '', 'h1'),
                ('rust_app_handle_add_spring', 'centrode_core.bridge.api.impl.[AppHandle]add_anchor_spring()', 'native/bridge/api.rs', 'Method', 'pub fn add_anchor_spring(&self)', '', 'h2')
        """)

    linker = FfiLinker(repository)
    edges_created = linker.link_scip_bridges()

    # Boilerplate freezed file should be excluded
    assert edges_created == 0

    db_conn.close()
