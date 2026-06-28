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


def test_auditor_upstream_propagation_and_path_tracing(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Set up config.json with propagation handler for 'layer'
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Application", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "handler": "propagation",
                    "propagation_direction": "upstream",
                    "weights": {
                        "Presentation": 1,
                        "Application": 2,
                        "Domain": 3,
                        "Infrastructure": 4
                    },
                    "rules": [
                        {"source": "Presentation", "target": "Infrastructure", "message": "Presentation layer transitively called Infrastructure layer"}
                    ]
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('presentation_sym', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('core_sym', 'lib/core/util.dart', 'Method', null, null, null),
                ('infra_sym', 'lib/infra/client.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
            VALUES
                ('core_sym', 'lib/ui/widget.dart', 45, 1, 45, 10, 2),
                ('infra_sym', 'lib/core/util.dart', 12, 1, 12, 10, 2),
                ('infra_sym', 'lib/infra/client.dart', 80, 1, 80, 10, 1)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('presentation_sym', 'core_sym', 'Calls'),
                ('core_sym', 'infra_sym', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    assert len(violations) == 1
    v = violations[0]
    assert "Presentation layer transitively called Infrastructure layer" in v["message"]
    # Check that it generated the transitive trace path
    assert "Path:" in v["message"]
    assert "1. lib/ui/widget.dart:L45 (symbol: presentation_sym)" in v["message"]
    assert "2. lib/core/util.dart:L12 (symbol: core_sym)" in v["message"]
    assert "3. lib/infra/client.dart:L80 (symbol: infra_sym)" in v["message"]

    db_conn.close()


def test_auditor_respects_propagation_barriers(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Set up config.json with propagation handler, and make 'Domain' a barrier
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Application", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "handler": "propagation",
                    "propagation_direction": "upstream",
                    "weights": {
                        "Presentation": 1,
                        "Application": 2,
                        "Domain": 3,
                        "Infrastructure": 4
                    },
                    "barriers": ["Domain"],
                    "rules": [
                        {"source": "Presentation", "target": "Infrastructure", "message": "Presentation layer transitively called Infrastructure layer"}
                    ]
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('presentation_sym', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('core_sym', 'lib/core/util.dart', 'Method', null, null, null),
                ('infra_sym', 'lib/infra/client.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('presentation_sym', 'core_sym', 'Calls'),
                ('core_sym', 'infra_sym', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    # The propagation should be blocked by 'core_sym' (which defaults to 'Domain', a barrier).
    # Thus, 'presentation_sym' won't inherit 'Infrastructure' and no violations will occur.
    assert len(violations) == 0

    db_conn.close()


def test_auditor_package_restrictions(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Set up config.json with a package restriction rule
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Domain", "conditions": {"path_prefix": "lib/core"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "rules": [
                        {
                            "rule_type": "package_restriction",
                            "source": "Domain",
                            "blocklist": ["package:flutter/*", "package:sqflite/*"],
                            "message": "Domain layer must not depend on database/UI framework packages."
                        }
                    ]
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('domain_sym', 'lib/core/model.dart', 'Class', null, null, null),
                ('package:flutter/src/widgets/framework.dart::Widget', null, 'Class', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('domain_sym', 'package:flutter/src/widgets/framework.dart::Widget', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    assert len(violations) == 1
    assert violations[0]["rule_id"] == "layer_pkg_domain"
    assert "Domain layer must not depend on database/UI framework packages" in violations[0]["message"]

    db_conn.close()


def test_auditor_naming_conventions(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Set up config.json with a naming convention rule
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}}
                    ],
                    "rules": [
                        {
                            "rule_type": "naming_convention",
                            "classification": "Presentation",
                            "name_suffix": "Widget",
                            "message": "All Presentation components must be suffixed with 'Widget'."
                        }
                    ]
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('package:project/lib/ui/widget.dart::MyWidget', 'lib/ui/widget.dart', 'Class', null, null, null),
                ('package:project/lib/ui/widget.dart::BadView', 'lib/ui/widget.dart', 'Class', null, null, null)
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    # 'MyWidget' is compliant, 'BadView' is not because it does not end with 'Widget'
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "naming_presentation"
    assert "BadView" in violations[0]["symbol"]
    assert "All Presentation components must be suffixed with 'Widget'" in violations[0]["message"]

    db_conn.close()
