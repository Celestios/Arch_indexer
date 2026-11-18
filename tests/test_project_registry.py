import os
import pytest
from pathlib import Path

from db.connection import DbConnection
from db.repository import Repository
from setup.initializer import initialize_workspace
from interface.project_registry import ProjectRegistry, normalize_path


@pytest.fixture(autouse=True)
def reset_registry(tmp_path, monkeypatch):
    global_dir = tmp_path / "global_arch"
    monkeypatch.setenv("ARCH_GLOBAL_DIR", str(global_dir))
    ProjectRegistry.reset_instance()
    yield
    ProjectRegistry.reset_instance()


def create_test_project(root: Path):
    initialize_workspace(root)
    conn = DbConnection(root / ".arch" / "arch.db")
    with conn.session() as s:
        s.execute("""
            INSERT INTO files (filepath, sha256, language, status, manual_status)
            VALUES ('src/test.py', 'hash1', 'python', 'COMPLIANT', 'COMPLIANT')
        """)
        s.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature)
            VALUES ('test_sym', 'test_sym', 'src/test.py', 'Function', 'def test_sym()')
        """)
    conn.close()


def test_project_registry_multi_project(tmp_path):
    p1 = tmp_path / "project1"
    p2 = tmp_path / "project2"
    create_test_project(p1)
    create_test_project(p2)

    reg = ProjectRegistry.get_instance()

    ctx1 = reg.register_project(p1, start_watcher=False)
    assert ctx1.root == p1.resolve()
    assert ctx1.repository is not None

    ctx2 = reg.register_project(p2, start_watcher=False)
    assert ctx2.root == p2.resolve()
    assert ctx2.repository is not None

    # Verify connection caching
    ctx1_again = reg.register_project(p1, start_watcher=False)
    assert ctx1_again is ctx1

    # Verify listing
    projs = reg.list_projects()
    assert len(projs) == 2
    roots = [p["root"] for p in projs]
    assert normalize_path(p1) in roots
    assert normalize_path(p2) in roots


def test_project_registry_resolve_cascade(tmp_path):
    p1 = tmp_path / "project1"
    p2 = tmp_path / "project2"
    create_test_project(p1)
    create_test_project(p2)

    reg = ProjectRegistry.get_instance()
    reg.register_project(p1, start_watcher=False)
    reg.register_project(p2, start_watcher=False)

    # 1. Explicit project_root
    assert reg.resolve_project(project_root=p1) == p1.resolve()
    assert reg.resolve_project(project_root=p2) == p2.resolve()

    # 2. Filepath under project2
    fp2 = p2 / "src" / "test.py"
    assert reg.resolve_project(filepath=fp2) == p2.resolve()


def test_project_registry_missing_db(tmp_path):
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir(parents=True, exist_ok=True)

    reg = ProjectRegistry.get_instance()
    with pytest.raises(FileNotFoundError, match="Arch database not found"):
        reg.register_project(empty_dir, start_watcher=False)


def test_project_registry_close_project(tmp_path):
    p1 = tmp_path / "project1"
    create_test_project(p1)

    reg = ProjectRegistry.get_instance()
    reg.register_project(p1, start_watcher=False)
    assert normalize_path(p1) in reg._projects

    closed = reg.close_project(p1)
    assert closed is True
    assert normalize_path(p1) not in reg._projects
