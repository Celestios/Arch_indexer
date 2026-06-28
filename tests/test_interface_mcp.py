import pytest
from pathlib import Path
from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor


def setup_workspace(tmp_path):
    """Helper to initialize workspace and return repo/connection."""
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def test_get_symbols_in_file(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('my_func', 'lib/ui/widget.dart', 'Method', 'my_func()', 'Docstring 1', null),
                ('other_func', 'lib/core/util.dart', 'Method', 'other_func()', 'Docstring 2', null)
        """)

    # Query existing file
    syms = repository.get_symbols_in_file("lib/ui/widget.dart")
    assert len(syms) == 1
    assert syms[0]["symbol"] == "my_func"
    assert syms[0]["signature"] == "my_func()"
    assert syms[0]["docstring"] == "Docstring 1"

    # Query with alternative separator
    syms_win = repository.get_symbols_in_file("lib\\ui\\widget.dart")
    assert len(syms_win) == 1
    assert syms_win[0]["symbol"] == "my_func"

    # Query non-existent file
    syms_none = repository.get_symbols_in_file("lib/ui/none.dart")
    assert len(syms_none) == 0

    db_conn.close()


def test_get_transitive_closure(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('A', 'B', 'Calls'),
                ('B', 'C', 'Calls'),
                ('C', 'D', 'Calls'),
                ('X', 'B', 'Calls')
        """)

    closure = repository.get_transitive_closure("B", max_depth=3)
    upstream = closure["upstream"]
    downstream = closure["downstream"]

    # Upstream of B should be A and X (direct, depth 1)
    assert any(u["symbol"] == "A" and u["depth"] == 1 for u in upstream)
    assert any(u["symbol"] == "X" and u["depth"] == 1 for u in upstream)

    # Downstream of B should be C (depth 1) and D (depth 2)
    assert any(d["symbol"] == "C" and d["depth"] == 1 for d in downstream)
    assert any(d["symbol"] == "D" and d["depth"] == 2 for d in downstream)

    db_conn.close()


def test_layer_aggregations(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('sym1', 'src/db/repo.py', 'Method', null, null, null),
                ('sym2', 'src/db/connection.py', 'Class', null, null, null),
                ('sym3', 'src/engines/scip.py', 'Method', null, null, null),
                ('sym4', 'src/main.py', 'Function', null, null, null)
        """)

    totals = repository.get_repo_totals()
    assert totals["symbols"] == 4
    
    kinds = repository.get_symbol_counts_by_kind()
    assert kinds["Method"] == 2
    assert kinds["Class"] == 1
    assert kinds["Function"] == 1

    prefixes = repository.get_symbols_by_file_prefix()
    assert prefixes["src/db/"] == 2
    assert prefixes["src/engines/"] == 1
    assert prefixes["src/"] == 1

    db_conn.close()


def test_auditor_filter(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('ui_widget', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('infra_client', 'lib/infra/client.dart', 'Method', null, null, null),
                ('other_ui', 'lib/other_ui/widget.dart', 'Method', null, null, null),
                ('infra_other', 'lib/infra/other.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('ui_widget', 'infra_client', 'Calls'),
                ('other_ui', 'infra_other', 'Calls')
        """)

    auditor = Auditor(repository, root)
    
    # Audit only lib/ui/
    violations_filtered = auditor.run_audit(filepath_filter="lib/ui/")
    assert len(violations_filtered) == 1
    assert violations_filtered[0]["symbol"] == "ui_widget"

    # Audit everything
    violations_all = auditor.run_audit()
    assert len(violations_all) == 1
    assert violations_all[0]["symbol"] == "ui_widget"

    db_conn.close()


def test_map_community_mapping(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('ui_a', 'lib/ui/widget.dart', 'Class', null, null, null),
                ('ui_b', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('ui_c', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('db_a', 'src/db/repo.py', 'Class', null, null, null),
                ('db_b', 'src/db/repo.py', 'Method', null, null, null),
                ('db_c', 'src/db/repo.py', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('ui_a', 'ui_b', 'Calls'),
                ('ui_b', 'ui_c', 'Calls'),
                ('db_a', 'db_b', 'Calls'),
                ('db_b', 'db_c', 'Calls'),
                ('ui_c', 'db_a', 'Calls')
        """)

    # Test map output
    out = mcp_server.map()
    assert "## Repository Architectural Blueprint Map" in out
    assert "Detected Architectural Communities" in out
    assert "Community: `lib/ui/` (3 symbol(s))" in out
    assert "Community: `src/db/` (3 symbol(s))" in out
    assert "Inter-Community Call Dependencies" in out
    assert "`lib/ui/` ──[1 call(s)]──> `src/db/`" in out

    db_conn.close()


def test_query_tool_multi_query(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    # Mock the embedder inside the query tool
    class MockEmbedder:
        def __init__(self, bin_dir):
            pass
        def embed(self, text):
            return [0.1, 0.2, 0.3]

    monkeypatch.setattr(mcp_server, "LocalEmbedder", MockEmbedder)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding)
            VALUES ('sym_a', 'src/db.py', 'Class', null, 'doc A', null, [0.1, 0.2, 0.3]::FLOAT[])
        """)

    # Test query with single string
    out_single = mcp_server.query("search query")
    assert 'Semantic Search Results for: "search query"' in out_single
    assert "sym_a" in out_single

    # Test query with list of strings
    out_multi = mcp_server.query(["first search", "second search"])
    assert 'Semantic Search Results for: "first search"' in out_multi
    assert 'Semantic Search Results for: "second search"' in out_multi
    assert "sym_a" in out_multi

    db_conn.close()


def test_mcp_tools_context(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('class_sym', 'lib/ui/widget.dart', 'Class', 'class Widget', 'A widget class', null),
                ('method_sym', 'lib/ui/widget.dart', 'Method', 'def draw()', 'Draws the widget', null)
        """)
        conn.execute("""
            INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
            VALUES
                ('class_sym', 'lib/ui/widget.dart', 10, 1, 20, 1, 1),
                ('method_sym', 'lib/ui/widget.dart', 15, 1, 18, 1, 1)
        """)

    # Test context tool
    out = mcp_server.context("lib/ui/widget.dart")
    assert "## File Index: `lib/ui/widget.dart`" in out
    assert "class_sym" in out
    assert "[L10-20]" in out
    assert "method_sym" in out
    assert "[L15-18]" in out

    db_conn.close()


def test_mcp_tools_impact(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('A', 'B', 'Calls'),
                ('B', 'C', 'Calls')
        """)

    out = mcp_server.impact("B", max_depth=2)
    assert "## Blast Radius for: `B`" in out
    assert "A" in out
    assert "C" in out
    assert "Path: `A` ──> `B`" in out
    assert "Path: `B` ──> `C`" in out

    db_conn.close()


def test_mcp_tools_audit(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    # Insert a violation manually in DB to verify audit formatting
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO compliance_rules (rule_id, description, severity)
            VALUES ('rules_test', 'presentation ui constraint', 'WARNING')
        """)
        conn.execute("""
            INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message)
            VALUES ('vi_1', 'rules_test', 'ui_widget', 'lib/ui/widget.dart', 10, 'call violation')
        """)

    # Mock the Auditor.run_audit method to return our manually inserted violation
    # since we want to test server.py's formatting logic
    def mock_run_audit(self, filepath_filter=None):
        return [{
            "violation_id": "vi_1",
            "rule_id": "rules_test",
            "symbol": "ui_widget",
            "filepath": "lib/ui/widget.dart",
            "line": 10,
            "message": "call violation"
        }]
    
    monkeypatch.setattr("auditor.analyzer.Auditor.run_audit", mock_run_audit)

    out = mcp_server.audit()
    assert "## Compliance Audit Report" in out
    assert "Active Violations (1)" in out
    assert "[rules_test]" in out
    assert "lib/ui/widget.dart:L10" in out
    assert "ui_widget" in out
    assert "call violation" in out

    db_conn.close()


def test_mcp_tools_trace_mocked(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    # Create CodeQL DB folder so it exists
    codeql_db_dir = root / ".arch" / "codeql_db"
    codeql_db_dir.mkdir(parents=True, exist_ok=True)

    # Mock CodeQlWrapper
    class MockCodeQlWrapper:
        def trace_data_flow(self, db_dir, source, sink):
            if source == "source_sym" and sink == "sink_sym":
                return [
                    {"symbol": "source_sym", "filepath": "src/source.py", "line": 5},
                    {"symbol": "sink_sym", "filepath": "src/sink.py", "line": 10}
                ]
            return []

    # Inject mock
    import sys
    # Add a mock class to engines.codeql_wrapper
    import engines.codeql_wrapper
    monkeypatch.setattr(engines.codeql_wrapper, "CodeQlWrapper", MockCodeQlWrapper)

    # Success case
    out = mcp_server.trace("source_sym", "sink_sym")
    assert "## Data Flow Trace: Path Found" in out
    assert "source_sym" in out
    assert "sink_sym" in out
    assert "src/source.py:L5" in out

    # Path not found case
    out_empty = mcp_server.trace("none", "none")
    assert "No flow path found" in out_empty

    db_conn.close()


def test_mcp_tools_database_missing(tmp_path, monkeypatch):
    import src.interface.server as mcp_server
    
    # Set DB_PATH to non-existent location
    non_existent = tmp_path / "missing_dir" / "missing.db"
    monkeypatch.setattr(mcp_server, "DB_PATH", non_existent)

    # All tools should return a clean error string instead of crashing
    assert "database not found" in mcp_server.query("search query")
    assert "database not found" in mcp_server.context("lib/file.dart")
    assert "database not found" in mcp_server.impact("symbol")
    assert "database not found" in mcp_server.audit()
    assert "database not found" in mcp_server.map()
    assert "database not found" in mcp_server.trace("src", "sink")
    assert "database not found" in mcp_server.report("overview")


def test_map_tool_empty_database(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    out = mcp_server.map()
    assert "Totals" in out
    assert "Files Indexed**: 0" in out
    assert "Symbols Registered**: 0" in out
    assert "No communities detected" in out

    db_conn.close()


def test_context_tool_empty_file(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    out = mcp_server.context("unindexed_file.py")
    assert "No indexed symbols found in file" in out

    db_conn.close()


def test_mcp_tools_report(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    # Add a mock violation
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO compliance_rules (rule_id, description, severity)
            VALUES ('test_rule', 'desc', 'CRITICAL')
        """)
        conn.execute("""
            INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message)
            VALUES ('v_id', 'test_rule', 'sym_a', 'src/db.py', 10, 'error message')
        """)

    # Test report tool
    out = mcp_server.report("compliance")
    assert "Compliance Violations Report" in out
    assert "sym_a" in out

    db_conn.close()


def test_mcp_tools_manual_status_and_fields(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    # Insert a file in the DB
    repository.upsert_file("lib/ui/widget.dart", "sha123", "dart")

    # 1. Test set_file_status
    out_status = mcp_server.set_file_status("lib/ui/widget.dart", "COMPLIANT", "Approved legacy module")
    assert "Successfully updated compliance status" in out_status
    assert "COMPLIANT" in out_status

    # Check database
    file_info = repository.get_file("lib/ui/widget.dart")
    assert file_info["manual_status"] == "COMPLIANT"
    assert file_info["justification"] == "Approved legacy module"

    # 2. Test set_file_fields
    out_fields = mcp_server.set_file_fields("lib/ui/widget.dart", {"pattern": "Widget", "tier": 1}, "Set annotations")
    assert "Successfully updated manual fields" in out_fields
    assert "Widget" in out_fields

    # Check database
    file_info_updated = repository.get_file("lib/ui/widget.dart")
    import json
    m_fields = json.loads(file_info_updated["manual_fields"])
    assert m_fields["pattern"] == "Widget"
    assert m_fields["tier"] == 1

    # 3. Test get_file_details
    out_details = mcp_server.get_file_details("lib/ui/widget.dart")
    assert "File Details:" in out_details
    assert "Widget" in out_details
    assert "COMPLIANT" in out_details

    db_conn.close()


def test_mcp_tools_violation_override(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)

    import src.interface.server as mcp_server
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", root)
    monkeypatch.setattr(mcp_server, "ARCH_DIR", root / ".arch")
    monkeypatch.setattr(mcp_server, "DB_PATH", root / ".arch" / "arch.db")

    # Insert rule, file, and violation
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO compliance_rules (rule_id, description, severity)
            VALUES ('rules_test', 'presentation ui constraint', 'WARNING')
        """)
        conn.execute("""
            INSERT INTO files (filepath, sha256, language)
            VALUES ('lib/ui/widget.dart', 'sha123', 'dart')
        """)

    out_override = mcp_server.set_violation_override("vi_1", "Approved exception")
    assert "Violation 'vi_1' overridden successfully" in out_override

    # Check DB overrides
    overrides = repository.get_violation_overrides()
    assert overrides["vi_1"] == "Approved exception"

    # Remove override
    out_remove = mcp_server.remove_violation_override("vi_1")
    assert "Successfully removed override" in out_remove

    # Check DB overrides again
    overrides2 = repository.get_violation_overrides()
    assert "vi_1" not in overrides2

    db_conn.close()



