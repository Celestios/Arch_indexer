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
