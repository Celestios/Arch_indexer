import json
from pathlib import Path
from setup.initializer import initialize_workspace, DEFAULT_CONFIG_JSON
from db.connection import DbConnection
from db.repository import Repository
from engines.ffi_linker import link_ffi_bridges, parse_callable_parts
from utils.arch_config import ArchConfig
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


def test_parse_callable_parts():
    cls_name, fn_name = parse_callable_parts("centrode_core.bridge.api.impl.[AppHandle]add_anchor_spring()")
    assert cls_name == "apphandle"
    assert fn_name == "addanchorspring"

    cls_name, fn_name = parse_callable_parts("lib.bridge.api.dart.AppHandle.addAnchorSpring()")
    assert cls_name == "apphandle"
    assert fn_name == "addanchorspring"

    cls_name, fn_name = parse_callable_parts("crate::AppHandle#new")
    assert cls_name == "apphandle"
    assert fn_name == "new"

    cls_name, fn_name = parse_callable_parts("lib.bridge.api.dart.AppHandle.newInstance()")
    assert cls_name == "apphandle"
    assert fn_name == "new"


def test_link_ffi_bridges_direct(tmp_path):
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

    edges_created = link_ffi_bridges(repository)
    assert edges_created == 3

    with db_conn.session() as conn:
        res = conn.execute(
            "SELECT source, target, relation, weight FROM edges WHERE relation = 'FFI_Binds' ORDER BY source"
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
        assert all(r[3] == 1.0 for r in res)

    db_conn.close()


def test_link_ffi_bridges_excludes_boilerplate(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('dart_gen_sym', 'lib.bridge.api.freezed.AppHandle.addAnchorSpring()', 'lib/bridge/api.freezed.dart', 'Method', 'void addAnchorSpring()', '', 'h1'),
                ('rust_app_handle_add_spring', 'centrode_core.bridge.api.impl.[AppHandle]add_anchor_spring()', 'native/bridge/api.rs', 'Method', 'pub fn add_anchor_spring(&self)', '', 'h2')
        """)

    edges_created = link_ffi_bridges(repository)
    assert edges_created == 0

    db_conn.close()


def test_link_ffi_bridges_clears_old_edges(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('dart_fn', 'lib.api.init()', 'lib/api.dart', 'Function', 'void init()', '', 'h1'),
                ('rust_fn', 'native.api.init()', 'native/api.rs', 'Function', 'pub fn init()', '', 'h2')
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation, weight)
            VALUES ('old_source', 'old_target', 'FFI_Binds', 0.5)
        """)

    edges_created = link_ffi_bridges(repository)
    assert edges_created == 1

    with db_conn.session() as conn:
        res = conn.execute("SELECT source, target, relation, weight FROM edges WHERE relation = 'FFI_Binds'").fetchall()
        assert len(res) == 1
        assert res[0][0] == "dart_fn"
        assert res[0][1] == "rust_fn"

    db_conn.close()


def test_link_ffi_bridges_explicit_config(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('custom_client', 'client.mismatched_name()', 'lib/client.dart', 'Function', 'void mismatched()', '', 'h1'),
                ('custom_native', 'native.different_name()', 'native/src.rs', 'Function', 'pub fn diff()', '', 'h2')
        """)

    config = ArchConfig(ffi_bindings={"custom_client": "custom_native"})
    edges_created = link_ffi_bridges(repository, config=config)
    assert edges_created == 1

    with db_conn.session() as conn:
        res = conn.execute("SELECT source, target, relation FROM edges WHERE relation = 'FFI_Binds'").fetchall()
        assert len(res) == 1
        assert res[0][0] == "custom_client"
        assert res[0][1] == "custom_native"

    db_conn.close()
