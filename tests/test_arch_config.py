import json
from pathlib import Path
from utils.arch_config import ArchConfig


class TestArchConfigApplicable:
    def test_get_applicable_config_exact_prefix(self):
        config = ArchConfig.from_dict({
            "src/core/": {"layer": "core"},
            "src/": {"layer": "app"},
        })
        result = config.get_applicable_config("src/core/utils.py")
        assert result.get("layer") == "core"

    def test_get_applicable_config_longest_prefix_wins(self):
        config = ArchConfig.from_dict({
            "src/": {"layer": "app"},
            "src/core/": {"layer": "core"},
            "src/core/db/": {"layer": "db"},
        })
        result = config.get_applicable_config("src/core/db/connection.py")
        assert result.get("layer") == "db"

    def test_get_applicable_config_root_fallback(self):
        config = ArchConfig.from_dict({
            ".": {"layer": "root"},
            "src/": {"layer": "app"},
        })
        result = config.get_applicable_config("README.md")
        assert result.get("layer") == "root"

    def test_get_applicable_config_no_match(self):
        config = ArchConfig.from_dict({
            "src/": {"layer": "app"},
        })
        result = config.get_applicable_config("lib/other.py")
        assert result is None

    def test_get_applicable_config_backslash_normalized(self):
        config = ArchConfig.from_dict({
            "src/core/": {"layer": "core"},
        })
        result = config.get_applicable_config("src\\core\\utils.py")
        assert result.get("layer") == "core"

    def test_find_applicable_config_on_dict(self):
        raw = {
            "src/core/": {"layer": "core"},
            "src/": {"layer": "app"},
        }
        res = ArchConfig.find_applicable_config("src/core/utils.py", raw)
        assert res == {"layer": "core"}


class TestArchConfigValidation:
    def test_validator_missing_config(self, tmp_path):
        cfg, res = ArchConfig.parse_and_validate(tmp_path)
        assert cfg is None
        assert not res["success"]
        assert len(res["errors"]) == 1
        assert "Configuration file not found" in res["errors"][0]

    def test_validator_invalid_json(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        config_file = arch_dir / "config.json"
        config_file.write_text("{ invalid json }", encoding="utf-8")

        cfg, res = ArchConfig.parse_and_validate(tmp_path)
        assert cfg is None
        assert not res["success"]
        assert len(res["errors"]) == 1
        assert "Failed to parse config.json as JSON" in res["errors"][0]

    def test_validator_valid_config(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        config_file = arch_dir / "config.json"

        valid_cfg = {
            "lib": {
                "manual_fields": {
                    "pattern": {
                        "values": ["Data Model", "Controller", "None"],
                        "default": "None",
                    }
                },
                "automatic_fields": {
                    "layer": {
                        "values": ["Presentation", "Domain", "Infrastructure"],
                        "default": "Domain",
                        "assignment_rules": [
                            {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                            {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}},
                        ],
                        "handler": "dependency_check",
                        "rules": [
                            {"source": "Presentation", "target": "Infrastructure", "message": "error"}
                        ],
                    }
                },
            }
        }
        config_file.write_text(json.dumps(valid_cfg), encoding="utf-8")

        cfg, res = ArchConfig.parse_and_validate(tmp_path)
        assert cfg is not None
        assert res["success"]
        assert not res["errors"]
        assert not res["warnings"]

    def test_validator_unreachable_value_warning(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        config_file = arch_dir / "config.json"

        unreachable_cfg = {
            "lib": {
                "automatic_fields": {
                    "layer": {
                        "values": ["Presentation", "Domain", "Infrastructure"],
                        "default": "Domain",
                        "assignment_rules": [
                            {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}}
                        ],
                    }
                }
            }
        }
        config_file.write_text(json.dumps(unreachable_cfg), encoding="utf-8")

        cfg, res = ArchConfig.parse_and_validate(tmp_path)
        assert cfg is not None
        assert res["success"]
        assert not res["errors"]
        assert len(res["warnings"]) == 1
        assert "Values that are defined but not used: ['Infrastructure']" in res["warnings"][0]

    def test_validator_referential_integrity_rules(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        config_file = arch_dir / "config.json"

        invalid_cfg = {
            "lib": {
                "automatic_fields": {
                    "layer": {
                        "values": ["Presentation", "Domain"],
                        "default": "Domain",
                        "handler": "dependency_check",
                        "rules": [
                            {"source": "InvalidSource", "target": "InvalidTarget", "message": "error"}
                        ],
                    }
                }
            }
        }
        config_file.write_text(json.dumps(invalid_cfg), encoding="utf-8")

        cfg, res = ArchConfig.parse_and_validate(tmp_path)
        assert cfg is None
        assert not res["success"]
        assert len(res["errors"]) == 2
        assert "rule source 'InvalidSource' is not in allowed values list" in res["errors"][0]
        assert "rule target 'InvalidTarget' is not in allowed values list" in res["errors"][1]

    def test_validator_propagation_barrier_role(self, tmp_path):
        arch_dir = tmp_path / ".arch"
        arch_dir.mkdir()
        config_file = arch_dir / "config.json"

        invalid_cfg = {
            "lib": {
                "manual_fields": {
                    "role": {
                        "values": ["UI", "Core"],
                        "default": "Core",
                    }
                },
                "automatic_fields": {
                    "layer": {
                        "values": ["Presentation", "Domain"],
                        "default": "Domain",
                        "handler": "propagation",
                        "barrier_field": "role",
                        "barriers": ["InvalidBarrier"],
                    }
                },
            }
        }
        config_file.write_text(json.dumps(invalid_cfg), encoding="utf-8")

        cfg, res = ArchConfig.parse_and_validate(tmp_path)
        assert cfg is None
        assert not res["success"]
        assert len(res["errors"]) == 1
        assert "barrier(s) ['InvalidBarrier'] are not in allowed values list ['UI', 'Core'] of barrier_field 'role'" in res["errors"][0]
