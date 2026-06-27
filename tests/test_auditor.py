import json
from pathlib import Path
from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor


def setup_workspace(tmp_path):
    """Helper to create a workspace and return (repository, db_conn, root)."""
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def test_auditor_returns_empty_when_no_rules(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    config_path = root / ".arch" / "config.json"
    config_path.write_text("{}")

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()
    assert violations == []

    db_conn.close()


def test_auditor_loads_config(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    auditor = Auditor(repository, root)
    config = auditor.load_config()

    assert "lib" in config
    assert "automatic_fields" in config["lib"]

    db_conn.close()


def test_auditor_detects_violation(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('presentation_sym', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('infra_sym', 'lib/infra/client.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('presentation_sym', 'infra_sym', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    assert len(violations) >= 1
    assert any("Presentation" in v["message"] and "Infrastructure" in v["message"]
               for v in violations)

    db_conn.close()


def test_auditor_no_false_positives(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('domain_sym', 'lib/core/model.dart', 'Class', null, null, null),
                ('infra_sym', 'lib/infra/client.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('domain_sym', 'infra_sym', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    assert len(violations) == 0

    db_conn.close()
