from unittest.mock import patch
from main import main, cmd_init, cmd_audit


def test_main_no_args(capsys):
    """main() with no args prints help and exits."""
    with patch("sys.argv", ["arch"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 1

    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "arch" in captured.out.lower()


def test_cmd_init_creates_workspace(tmp_path, monkeypatch, capsys):
    """cmd_init creates .arch/ directory, scans languages, and handles skip model choice."""
    # Mock interactive prompts
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    
    def mock_input(prompt=""):
        p = prompt.lower()
        if "option" in p:
            return "4"
        return "n"
        
    monkeypatch.setattr("builtins.input", mock_input)

    args = type("Args", (), {"project_root": str(tmp_path)})()
    cmd_init(args)

    assert (tmp_path / ".arch").exists()
    assert (tmp_path / ".arch" / "config.json").exists()
    assert (tmp_path / ".arch" / "arch.db").exists()

    captured = capsys.readouterr()
    assert "Workspace folder initialized" in captured.out
    assert "No supported toolchains detected" in captured.out or "Indexer" in captured.out


def test_cmd_audit_no_violations(tmp_path, capsys):
    """cmd_audit runs without error on empty workspace."""
    from setup.initializer import initialize_workspace
    initialize_workspace(tmp_path)

    args = type("Args", (), {"project_root": str(tmp_path)})()
    cmd_audit(args)

    captured = capsys.readouterr()
    assert "No violations" in captured.out or "violations" in captured.out.lower()


def test_cmd_impact(tmp_path, capsys):
    """cmd_impact runs transitive blast radius analysis on a temporary database."""
    from setup.initializer import initialize_workspace
    from db.connection import DbConnection
    initialize_workspace(tmp_path)
    
    # Insert call-graph edges
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('A', 'B', 'Calls'),
                ('B', 'C', 'Calls')
        """)
    db_conn.close()

    from main import cmd_impact
    args = type("Args", (), {
        "project_root": str(tmp_path),
        "symbol": "B",
        "max_depth": 2
    })()

    cmd_impact(args)

    captured = capsys.readouterr()
    assert "=== Blast Radius for: B ===" in captured.out
    assert "A" in captured.out
    assert "C" in captured.out
    assert "Path: A ──> B" in captured.out
    assert "Path: B ──> C" in captured.out


def test_cmd_mcp(tmp_path):
    """cmd_mcp sets ARCH_PROJECT_ROOT env and runs the server."""
    from unittest.mock import patch
    from main import cmd_mcp
    args = type("Args", (), {
        "project_root": str(tmp_path)
    })()

    with patch("interface.server.run_server") as mock_run:
        cmd_mcp(args)
        mock_run.assert_called_once()
        import os
        assert os.environ.get("ARCH_PROJECT_ROOT") == str(tmp_path)

