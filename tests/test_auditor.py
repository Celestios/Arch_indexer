import json
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


from utils.arch_config import ArchConfig


def test_auditor_loads_config(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    auditor = Auditor(repository, root)
    config = auditor.load_config()

    assert isinstance(config, (dict, ArchConfig))

    db_conn.close()


def test_auditor_detects_violation(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    config = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Application", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "handler": "dependency_check",
                    "rules": [
                        {"source": "Presentation", "target": "Infrastructure", "message": "Presentation layer cannot directly call Infrastructure layer"}
                    ]
                }
            }
        }
    }
    with open(root / ".arch" / "config.json", "w") as f:
        json.dump(config, f)

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


def test_auditor_manual_status_logical_flag(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Insert files and symbols
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO files (filepath, sha256, language, status, manual_status, pending_audit)
            VALUES ('lib/ui/widget.dart', 'hash123', 'dart', 'COMPLIANT', 'COMPLIANT', false)
        """)
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

    # AI logical audit flags a file as VIOLATION_DETECTED
    repository.files.update_file_manual_status('lib/ui/widget.dart', 'VIOLATION_DETECTED', 'Missing security validation in widget')
    
    # Add a manual violation
    repository.compliance.add_violation(
        violation_id="manual_v1",
        rule_id="logical_audit",
        symbol=None,
        filepath='lib/ui/widget.dart',
        line=1,
        message='Missing security validation in widget',
        origin="manual"
    )

    # Verify manual status and justification are preserved in DB
    file_metadata = repository.files.get_all_files_metadata()
    assert file_metadata['lib/ui/widget.dart']['manual_status'] == 'VIOLATION_DETECTED'
    assert file_metadata['lib/ui/widget.dart']['justification'] == 'Missing security validation in widget'

    # Run audit - verify manual violation is returned in get_violations
    auditor = Auditor(repository, root)
    violations = auditor.run_audit()
    
    all_v = repository.compliance.get_violations()
    manual_v = [v for v in all_v if v["origin"] == "manual"]
    assert len(manual_v) == 1
    assert manual_v[0]["message"] == 'Missing security validation in widget'

    # Clear manual status back to COMPLIANT
    repository.files.update_file_manual_status('lib/ui/widget.dart', 'COMPLIANT')
    repository.compliance.delete_manual_violations('lib/ui/widget.dart')
    
    all_v2 = repository.compliance.get_violations()
    manual_v2 = [v for v in all_v2 if v["origin"] == "manual"]
    assert len(manual_v2) == 0

    db_conn.close()


def test_auditor_change_triggered_pending_audit(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # 1. Insert new file -> should start as pending_audit = True
    repository.files.upsert_file('lib/ui/widget.dart', 'hash111', 'dart')
    
    file_info = repository.files.get_file('lib/ui/widget.dart')
    assert file_info['pending_audit'] is True
    assert file_info['manual_status'] == 'COMPLIANT'

    # 2. AI audits and sets to COMPLIANT -> should clear pending_audit
    repository.files.update_file_manual_status('lib/ui/widget.dart', 'COMPLIANT', 'Audited and verified')
    file_info_audited = repository.files.get_file('lib/ui/widget.dart')
    assert file_info_audited['pending_audit'] is False
    assert file_info_audited['manual_status'] == 'COMPLIANT'

    # 3. File re-indexed with same hash -> pending_audit remains False
    repository.files.upsert_file('lib/ui/widget.dart', 'hash111', 'dart')
    file_info_same = repository.files.get_file('lib/ui/widget.dart')
    assert file_info_same['pending_audit'] is False

    # 4. File re-indexed with different hash -> pending_audit reset to True, manual_status stays COMPLIANT
    repository.files.upsert_file('lib/ui/widget.dart', 'hash222', 'dart')
    file_info_changed = repository.files.get_file('lib/ui/widget.dart')
    assert file_info_changed['pending_audit'] is True
    assert file_info_changed['manual_status'] == 'COMPLIANT'
    assert 'File modified' in file_info_changed['justification']

    db_conn.close()


def test_change_triggered_audit_flags_reset_on_change(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Write a config with reset_on_change manual field
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "manual_fields": {
                "ai_summary": {
                    "default": "No summary yet",
                    "reset_on_change": True
                },
                "stability": {
                    "default": "stable",
                    "reset_on_change": False
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    # Insert file with manual fields populated
    manual_fields_str = json.dumps({"ai_summary": "Initial summary content", "stability": "experimental"})
    with db_conn.session() as conn:
        conn.execute(
            """
            INSERT INTO files (filepath, sha256, language, status, manual_status, pending_audit, manual_fields, justification)
            VALUES ('lib/ui/widget.dart', 'hash111', 'dart', 'COMPLIANT', 'COMPLIANT', false, ?, 'approved')
            """,
            (manual_fields_str,)
        )

    # Force a hash change update
    repository.files.upsert_file('lib/ui/widget.dart', 'hash222', 'dart')

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    # Verify that:
    # 1. ai_summary reset to default
    # 2. stability remains experimental
    # 3. pending_audit violation generated
    file_info = repository.files.get_file('lib/ui/widget.dart')
    m_fields = file_info['manual_fields'] if isinstance(file_info['manual_fields'], dict) else json.loads(file_info['manual_fields'])
    assert m_fields['ai_summary'] == 'No summary yet'
    assert m_fields['stability'] == 'experimental'
    assert file_info['pending_audit'] is True
    
    assert any(v['rule_id'] == 'pending_audit' and v['filepath'] == 'lib/ui/widget.dart' for v in violations)

    db_conn.close()


def test_change_triggered_audit_flags_invalid_value(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Write config defining restricted values
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "manual_fields": {
                "pattern": {
                    "values": ["Controller", "Service", "None"],
                    "default": "None"
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    # Insert file with invalid manual field value
    manual_fields_str = json.dumps({"pattern": "InvalidValue"})
    with db_conn.session() as conn:
        conn.execute(
            """
            INSERT INTO files (filepath, sha256, language, status, manual_status, pending_audit, manual_fields, justification)
            VALUES ('lib/ui/widget.dart', 'hash111', 'dart', 'COMPLIANT', 'COMPLIANT', false, ?, 'approved')
            """,
            (manual_fields_str,)
        )

    # Run audit and verify it resets the invalid value and marks pending_audit = True
    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    file_info = repository.files.get_file('lib/ui/widget.dart')
    m_fields = file_info['manual_fields'] if isinstance(file_info['manual_fields'], dict) else json.loads(file_info['manual_fields'])
    assert m_fields['pattern'] == 'None'
    assert file_info['pending_audit'] is True

    db_conn.close()


def test_auditor_manual_fields_override_automatic_and_propagate(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Set up config.json with a propagation handler for 'layer'
    config_path = root / ".arch" / "config.json"
    config_data = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "handler": "propagation",
                    "propagation_direction": "upstream",
                    "weights": {
                        "Presentation": 1,
                        "Domain": 2,
                        "Infrastructure": 3
                    },
                    "rules": [
                        {"source": "Presentation", "target": "Infrastructure", "message": "Violation Presentation calling Infrastructure"}
                    ]
                }
            }
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO files (filepath, sha256, language, status, pending_audit, manual_fields)
            VALUES 
                ('lib/ui/widget.dart', 'h1', 'dart', 'COMPLIANT', false, '{}'),
                ('lib/core/helper.dart', 'h2', 'dart', 'COMPLIANT', false, '{"layer": "Infrastructure"}'),
                ('lib/infra/client.dart', 'h3', 'dart', 'COMPLIANT', false, '{}')
        """)
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('presentation_sym', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('core_sym', 'lib/core/helper.dart', 'Method', null, null, null),
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

    assert len(violations) == 1
    assert "Violation Presentation calling Infrastructure" in violations[0]["message"]

    db_conn.close()

