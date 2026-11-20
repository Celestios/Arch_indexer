from unittest.mock import MagicMock, call
from auditor.field_validator import FieldValidator


def _make_validator():
    repo = MagicMock()
    config_loader = MagicMock()
    return FieldValidator(repo, config_loader), repo, config_loader


class TestResetInvalidManualFields:
    def test_no_files_no_action(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {}
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_not_called()

    def test_resets_disallowed_value(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {
                "manual_fields": {"tier": "super_critical"},
                "justification": "",
                "pending_audit": False,
            }
        }
        cl.get_applicable_config.return_value = {
            "manual_fields": {
                "tier": {
                    "default": "normal",
                    "values": ["normal", "low", "high"],
                }
            }
        }
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_called_once()
        args = repo.workspace.set_manual_fields.call_args
        assert args[0][0] == "src/main.py"
        assert args[0][1]["tier"] == "normal"
        repo.workspace.mark_file_for_audit.assert_called_once()

    def test_keeps_allowed_value(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {
                "manual_fields": {"tier": "high"},
                "justification": "",
                "pending_audit": False,
            }
        }
        cl.get_applicable_config.return_value = {
            "manual_fields": {
                "tier": {
                    "default": "normal",
                    "values": ["normal", "low", "high"],
                }
            }
        }
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_not_called()

    def test_reset_on_change_triggers(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {
                "manual_fields": {"tier": "custom"},
                "justification": "File modified, pending re-audit",
                "pending_audit": True,
            }
        }
        cl.get_applicable_config.return_value = {
            "manual_fields": {
                "tier": {
                    "default": "normal",
                    "values": ["normal", "low", "high"],
                    "reset_on_change": True,
                }
            }
        }
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_called_once()
        args = repo.workspace.set_manual_fields.call_args
        assert args[0][1]["tier"] == "normal"

    def test_reset_on_change_skips_when_not_modified(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {
                "manual_fields": {"tier": "high"},
                "justification": "Some other reason",
                "pending_audit": True,
            }
        }
        cl.get_applicable_config.return_value = {
            "manual_fields": {
                "tier": {
                    "default": "normal",
                    "values": ["normal", "low", "high"],
                    "reset_on_change": True,
                }
            }
        }
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_not_called()

    def test_no_applicable_config_skips(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "lib/other.py": {
                "manual_fields": {"tier": "bad"},
                "justification": "",
                "pending_audit": False,
            }
        }
        cl.get_applicable_config.return_value = None
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_not_called()

    def test_no_manual_fields_in_config(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {
                "manual_fields": {},
                "justification": "",
                "pending_audit": False,
            }
        }
        cl.get_applicable_config.return_value = {"automatic_fields": {}}
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_not_called()

    def test_multiple_files_mixed_states(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/good.py": {
                "manual_fields": {"tier": "normal"},
                "justification": "",
                "pending_audit": False,
            },
            "src/bad.py": {
                "manual_fields": {"tier": "invalid"},
                "justification": "",
                "pending_audit": False,
            },
        }
        cl.get_applicable_config.return_value = {
            "manual_fields": {
                "tier": {
                    "default": "normal",
                    "values": ["normal", "low"],
                }
            }
        }
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_called_once()
        args = repo.workspace.set_manual_fields.call_args
        assert args[0][0] == "src/bad.py"

    def test_no_current_manual_fields(self):
        fv, repo, cl = _make_validator()
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {
                "manual_fields": None,
                "justification": "",
                "pending_audit": False,
            }
        }
        cl.get_applicable_config.return_value = {
            "manual_fields": {
                "tier": {
                    "default": "normal",
                    "values": ["normal"],
                }
            }
        }
        fv.reset_invalid_manual_fields({"src/": {}})
        repo.workspace.set_manual_fields.assert_not_called()
