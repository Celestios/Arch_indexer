from unittest.mock import MagicMock
from auditor.classifier import SymbolClassifier


def _make_classifier(mock_repo=None):
    repo = mock_repo or MagicMock()
    return SymbolClassifier(repo)


class TestEvaluateConditions:
    def test_no_conditions_returns_true(self):
        clf = _make_classifier()
        result = clf.evaluate_conditions({"symbol": "foo", "filepath": "a.py"}, {}, [])
        assert result is True

    def test_path_prefix_match(self):
        clf = _make_classifier()
        info = {"symbol": "foo", "filepath": "src/core/utils.py"}
        assert clf.evaluate_conditions(info, {"path_prefix": "src/"}, []) is True

    def test_path_prefix_no_match(self):
        clf = _make_classifier()
        info = {"symbol": "foo", "filepath": "lib/other.py"}
        assert clf.evaluate_conditions(info, {"path_prefix": "src/"}, []) is False

    def test_path_prefix_no_filepath(self):
        clf = _make_classifier()
        info = {"symbol": "foo"}
        assert clf.evaluate_conditions(info, {"path_prefix": "src/"}, []) is False

    def test_path_prefix_backslash_normalized(self):
        clf = _make_classifier()
        info = {"symbol": "foo", "filepath": "src\\core\\utils.py"}
        assert clf.evaluate_conditions(info, {"path_prefix": "src/"}, []) is True

    def test_class_suffix_match(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::MyService", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"class_suffix": "Service"}, []) is True

    def test_class_suffix_no_match(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::MyHandler", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"class_suffix": "Service"}, []) is False

    def test_class_contains_match(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::UserService", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"class_contains": "User"}, []) is True

    def test_class_contains_no_match(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::OrderService", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"class_contains": "User"}, []) is False

    def test_name_contains_match(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::process_order", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"name_contains": "order"}, []) is True

    def test_name_contains_no_match(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::process_payment", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"name_contains": "order"}, []) is False

    def test_calls_prefix_match(self):
        mock_repo = MagicMock()
        mock_repo.symbols.get_symbol.return_value = {"filepath": "src/db/query.py"}
        clf = _make_classifier(mock_repo)
        info = {"symbol": "ns foo::fetch_data", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"calls_prefix": "src/"}, ["target_sym"]) is True

    def test_calls_prefix_no_match(self):
        mock_repo = MagicMock()
        mock_repo.symbols.get_symbol.return_value = {"filepath": "lib/other.py"}
        clf = _make_classifier(mock_repo)
        info = {"symbol": "ns foo::fetch_data", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"calls_prefix": "src/"}, ["target_sym"]) is False

    def test_calls_prefix_no_targets(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::fetch_data", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"calls_prefix": "src/"}, []) is False

    def test_calls_prefix_symbol_not_found(self):
        mock_repo = MagicMock()
        mock_repo.symbols.get_symbol.return_value = None
        clf = _make_classifier(mock_repo)
        info = {"symbol": "ns foo::fetch_data", "filepath": "a.py"}
        assert clf.evaluate_conditions(info, {"calls_prefix": "src/"}, ["missing"]) is False

    def test_combined_conditions_all_pass(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::UserService", "filepath": "src/core/service.py"}
        conditions = {"path_prefix": "src/", "class_suffix": "Service"}
        assert clf.evaluate_conditions(info, conditions, []) is True

    def test_combined_conditions_one_fails(self):
        clf = _make_classifier()
        info = {"symbol": "ns foo::UserService", "filepath": "lib/core/service.py"}
        conditions = {"path_prefix": "src/", "class_suffix": "Service"}
        assert clf.evaluate_conditions(info, conditions, []) is False


class TestAssignAutomaticFields:
    def test_returns_default_when_no_rules_match(self):
        clf = _make_classifier()
        prefix_conf = {
            "automatic_fields": {
                "layer": {
                    "default": "unknown",
                    "assignment_rules": [
                        {"value": "core", "conditions": {"path_prefix": "src/core/"}}
                    ]
                }
            }
        }
        info = {"symbol": "foo", "filepath": "src/other/foo.py"}
        result = clf.assign_automatic_fields(info, prefix_conf, [])
        assert result == {"layer": "unknown"}

    def test_first_matching_rule_wins(self):
        clf = _make_classifier()
        prefix_conf = {
            "automatic_fields": {
                "layer": {
                    "default": "unknown",
                    "assignment_rules": [
                        {"value": "core", "conditions": {"path_prefix": "src/core/"}},
                        {"value": "infra", "conditions": {"path_prefix": "src/"}}
                    ]
                }
            }
        }
        info = {"symbol": "foo", "filepath": "src/core/db.py"}
        result = clf.assign_automatic_fields(info, prefix_conf, [])
        assert result == {"layer": "core"}

    def test_multiple_fields(self):
        clf = _make_classifier()
        prefix_conf = {
            "automatic_fields": {
                "layer": {
                    "default": "unknown",
                    "assignment_rules": [
                        {"value": "core", "conditions": {"path_prefix": "src/"}}
                    ]
                },
                "role": {
                    "default": "module",
                    "assignment_rules": [
                        {"value": "service", "conditions": {"class_suffix": "Service"}}
                    ]
                }
            }
        }
        info = {"symbol": "ns foo::UserService", "filepath": "src/service.py"}
        result = clf.assign_automatic_fields(info, prefix_conf, [])
        assert result["layer"] == "core"
        assert result["role"] == "service"

    def test_empty_automatic_fields(self):
        clf = _make_classifier()
        info = {"symbol": "foo", "filepath": "a.py"}
        result = clf.assign_automatic_fields(info, {}, [])
        assert result == {}

    def test_scfi_name_extraction(self):
        clf = _make_classifier()
        info = {"symbol": "rust crate::module::MyStruct", "filepath": "a.py"}
        prefix_conf = {
            "automatic_fields": {
                "layer": {
                    "default": "unknown",
                    "assignment_rules": [
                        {"value": "core", "conditions": {"class_suffix": "Struct"}}
                    ]
                }
            }
        }
        result = clf.assign_automatic_fields(info, prefix_conf, [])
        assert result["layer"] == "core"
