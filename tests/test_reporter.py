import pytest
from db.repository import Repository
from db.connection import DbConnection
from setup.initializer import initialize_workspace
from reporter.generator import Reporter, BaseReport

def setup_workspace(tmp_path):
    root = tmp_path
    initialize_workspace(root)
    db_conn = DbConnection(root / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, root

def test_reporter_list_reports(tmp_path):
    repo, db_conn, root = setup_workspace(tmp_path)
    reporter = Reporter(repo)
    
    assert "overview" in reporter.list_reports()
    assert "compliance" in reporter.list_reports()
    
    db_conn.close()

def test_reporter_custom_registration(tmp_path):
    repo, db_conn, root = setup_workspace(tmp_path)
    reporter = Reporter(repo)
    
    class CustomReport(BaseReport):
        def generate(self):
            return {"key": "value"}
        def to_markdown(self, data):
            return f"Custom: {data['key']}"
            
    reporter.register_report("custom", CustomReport)
    assert "custom" in reporter.list_reports()
    
    out = reporter.generate_report("custom", "markdown")
    assert out == "Custom: value"
    
    out_json = reporter.generate_report("custom", "json")
    assert '"key": "value"' in out_json
    
    db_conn.close()

def test_overview_report_generation(tmp_path):
    repo, db_conn, root = setup_workspace(tmp_path)
    reporter = Reporter(repo)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('sym_a', 'src/db.py', 'Class', null, null, null),
                ('sym_b', 'src/db.py', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('sym_a', 'sym_b', 'Calls')
        """)

    out = reporter.generate_report("overview", "markdown")
    assert "Workspace Overview Report" in out
    assert "Files Indexed" in out
    assert "Symbols Registered" in out
    assert "Class" in out
    assert "src" in out or "db.py" in out
    assert "Workspace Dependency Call-Flow" in out
    assert "```mermaid" in out

    out_json = reporter.generate_report("overview", "json")
    assert '"symbols":' in out_json
    
    db_conn.close()

def test_compliance_report_generation(tmp_path):
    repo, db_conn, root = setup_workspace(tmp_path)
    reporter = Reporter(repo)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO compliance_rules (rule_id, description, severity)
            VALUES ('test_rule', 'desc', 'CRITICAL')
        """)
        conn.execute("""
            INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message)
            VALUES ('v_id', 'test_rule', 'sym_a', 'src/db.py', 10, 'error message')
        """)

    out = reporter.generate_report("compliance", "markdown")
    assert "Compliance Violations Report" in out
    assert "Critical Errors" in out
    assert "[test_rule]" in out
    assert "sym_a" in out
    assert "error message" in out

    out_json = reporter.generate_report("compliance", "json")
    assert '"critical": 1' in out_json
    
    db_conn.close()

def test_reporter_invalid_name(tmp_path):
    repo, db_conn, root = setup_workspace(tmp_path)
    reporter = Reporter(repo)
    
    with pytest.raises(KeyError):
        reporter.generate_report("non_existent", "markdown")
        
    db_conn.close()
