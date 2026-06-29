import json
from auditor.validator import ConfigValidator

def test_validator_missing_config(tmp_path):
    validator = ConfigValidator(tmp_path)
    res = validator.validate()
    assert not res["success"]
    assert len(res["errors"]) == 1
    assert "Configuration file not found" in res["errors"][0]

def test_validator_invalid_json(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config_file = arch_dir / "config.json"
    config_file.write_text("{ invalid json }", encoding="utf-8")

    validator = ConfigValidator(tmp_path)
    res = validator.validate()
    assert not res["success"]
    assert len(res["errors"]) == 1
    assert "Failed to parse config.json as JSON" in res["errors"][0]

def test_validator_valid_config(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config_file = arch_dir / "config.json"
    
    valid_cfg = {
        "lib": {
            "manual_fields": {
                "pattern": {
                    "values": ["Data Model", "Controller", "None"],
                    "default": "None"
                }
            },
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "handler": "dependency_check",
                    "rules": [
                        {"source": "Presentation", "target": "Infrastructure", "message": "error"}
                    ]
                }
            }
        }
    }
    config_file.write_text(json.dumps(valid_cfg), encoding="utf-8")

    validator = ConfigValidator(tmp_path)
    res = validator.validate()
    assert res["success"]
    assert not res["errors"]
    assert not res["warnings"]

def test_validator_unreachable_value_warning(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config_file = arch_dir / "config.json"

    # Unreachable: 'Infrastructure' is allowed but is not default ('Domain') and has no assignment rules.
    unreachable_cfg = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}}
                    ]
                }
            }
        }
    }
    config_file.write_text(json.dumps(unreachable_cfg), encoding="utf-8")

    validator = ConfigValidator(tmp_path)
    res = validator.validate()
    assert res["success"]  # Reachability warnings do not cause validation failure
    assert not res["errors"]
    assert len(res["warnings"]) == 1
    assert "Values that are defined but not used: ['Infrastructure']" in res["warnings"][0]

def test_validator_referential_integrity_rules(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config_file = arch_dir / "config.json"

    # Rules source 'InvalidSource' and target 'InvalidTarget' are not in values list
    invalid_cfg = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain"],
                    "default": "Domain",
                    "handler": "dependency_check",
                    "rules": [
                        {"source": "InvalidSource", "target": "InvalidTarget", "message": "error"}
                    ]
                }
            }
        }
    }
    config_file.write_text(json.dumps(invalid_cfg), encoding="utf-8")

    validator = ConfigValidator(tmp_path)
    res = validator.validate()
    assert not res["success"]
    assert len(res["errors"]) == 2
    assert "rule source 'InvalidSource' is not in allowed values list" in res["errors"][0]
    assert "rule target 'InvalidTarget' is not in allowed values list" in res["errors"][1]

def test_validator_propagation_barrier_role(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config_file = arch_dir / "config.json"

    # Field 'layer' specifies barriers ('InvalidBarrier') not in allowed values of barrier_field 'role'
    invalid_cfg = {
        "lib": {
            "manual_fields": {
                "role": {
                    "values": ["UI", "Core"],
                    "default": "Core"
                }
            },
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Domain"],
                    "default": "Domain",
                    "handler": "propagation",
                    "barrier_field": "role",
                    "barriers": ["InvalidBarrier"]
                }
            }
        }
    }
    config_file.write_text(json.dumps(invalid_cfg), encoding="utf-8")

    validator = ConfigValidator(tmp_path)
    res = validator.validate()
    assert not res["success"]
    assert len(res["errors"]) == 1
    assert "barrier(s) ['InvalidBarrier'] are not in allowed values list ['UI', 'Core'] of barrier_field 'role'" in res["errors"][0]
