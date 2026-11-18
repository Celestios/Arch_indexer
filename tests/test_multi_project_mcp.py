import pytest
from pathlib import Path

from db.connection import DbConnection
from setup.initializer import initialize_workspace
from interface.project_registry import ProjectRegistry
import src.interface.server as mcp_server


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    global_dir = tmp_path / "global_arch"
    monkeypatch.setenv("ARCH_GLOBAL_DIR", str(global_dir))
    ProjectRegistry.reset_instance()
    yield
    ProjectRegistry.reset_instance()


def populate_project(root: Path, file_name: str, sym_name: str):
    initialize_workspace(root)
    conn = DbConnection(root / ".arch" / "arch.db")
    with conn.session() as s:
        s.execute("""
            INSERT INTO files (filepath, sha256, language, status, manual_status)
            VALUES (?, 'hash1', 'python', 'COMPLIANT', 'COMPLIANT')
        """, (f"src/{file_name}",))
        s.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature)
            VALUES (?, ?, ?, 'Function', ?)
        """, (sym_name, sym_name, f"src/{file_name}", f"def {sym_name}()"))
    conn.close()


def test_mcp_multi_project_routing(tmp_path, monkeypatch):
    p1 = tmp_path / "app_alpha"
    p2 = tmp_path / "app_beta"
    populate_project(p1, "alpha.py", "run_alpha")
    populate_project(p2, "beta.py", "run_beta")

    # 1. Query with explicit project_root
    out_p1 = mcp_server.lookup("run_alpha", project_root=str(p1))
    assert "run_alpha" in out_p1
    assert "src/alpha.py" in out_p1

    out_p2 = mcp_server.lookup("run_beta", project_root=str(p2))
    assert "run_beta" in out_p2
    assert "src/beta.py" in out_p2

    # Cross-query should not find symbols
    out_cross = mcp_server.lookup("run_alpha", project_root=str(p2))
    assert "run_alpha" not in out_cross or "No files or symbols matched" in out_cross

    # 2. Query with nested subdirectory project_root (tree-walking verification)
    sub_dir = p1 / "src" / "nested"
    sub_dir.mkdir(parents=True, exist_ok=True)
    out_walkup = mcp_server.lookup("run_alpha", project_root=str(sub_dir))
    assert "run_alpha" in out_walkup

    # 3. Query context with filepath inference (tree-walking from file)
    ctx_p1 = mcp_server.context(str(p1 / "src" / "alpha.py"))
    assert "run_alpha" in ctx_p1

    ctx_p2 = mcp_server.context(str(p2 / "src" / "beta.py"))
    assert "run_beta" in ctx_p2

    # 4. Automatic tree-walking from CWD
    (p2 / "src").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(p2 / "src")
    out_cwd = mcp_server.lookup("run_beta")
    assert "run_beta" in out_cwd


def test_mcp_graph_tool(tmp_path):
    p = tmp_path / "app_graph"
    populate_project(p, "service.py", "serve_traffic")

    res = mcp_server.graph(project_root=str(p), scope=None)
    assert "Successfully generated architecture circuit visualizer" in res
    assert (p / "circuit_board.html").exists()
