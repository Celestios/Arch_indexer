"""Tests for all registry modules."""
import pytest


class TestLanguageRegistry:
    """Tests for LanguageRegistry."""

    def setup_method(self):
        from engines.registry import LanguageRegistry
        LanguageRegistry.clear()
        # Re-register built-in languages (backend required for list_languages)
        LanguageRegistry.register("rust", backend=object, extensions=[".rs"], tool_names=["Cargo.toml"])
        LanguageRegistry.register("dart", backend=object, extensions=[".dart"], tool_names=["pubspec.yaml"])
        LanguageRegistry.register("python", backend=object, extensions=[".py"], tool_names=["pyproject.toml"])

    def test_register_language(self):
        from engines.registry import LanguageRegistry
        LanguageRegistry.register("go", backend=object, extensions=[".go"], tool_names=["go.mod"])
        assert "go" in LanguageRegistry.list_languages()

    def test_detect_language_from_extension(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language("main.rs") == "rust"
        assert LanguageRegistry.detect_language("app.dart") == "dart"
        assert LanguageRegistry.detect_language("utils.py") == "python"

    def test_detect_language_unknown(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language("file.xyz") is None

    def test_detect_language_from_name(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language_from_name("Cargo.toml") == "rust"
        assert LanguageRegistry.detect_language_from_name("pubspec.yaml") == "dart"

    def test_list_languages(self):
        from engines.registry import LanguageRegistry
        langs = LanguageRegistry.list_languages()
        assert "rust" in langs
        assert "dart" in langs
        assert "python" in langs

    def test_clear_resets(self):
        from engines.registry import LanguageRegistry
        LanguageRegistry.clear()
        assert len(LanguageRegistry.list_languages()) == 0


class TestViolationCheckerRegistry:
    """Tests for ViolationCheckerRegistry."""

    def setup_method(self):
        from auditor.registry import ViolationCheckerRegistry
        ViolationCheckerRegistry.clear()

    def test_register_checker(self):
        from auditor.registry import ViolationCheckerRegistry
        checker = {"check": lambda: []}
        ViolationCheckerRegistry.register(checker)
        assert len(ViolationCheckerRegistry.get_all()) == 1

    def test_get_all_returns_copy(self):
        from auditor.registry import ViolationCheckerRegistry
        checker = {"check": lambda: []}
        ViolationCheckerRegistry.register(checker)
        result = ViolationCheckerRegistry.get_all()
        result.clear()  # Modify the copy
        assert len(ViolationCheckerRegistry.get_all()) == 1  # Original unchanged

    def test_register_multiple(self):
        from auditor.registry import ViolationCheckerRegistry
        c1, c2, c3 = {"name": "a"}, {"name": "b"}, {"name": "c"}
        ViolationCheckerRegistry.register(c1)
        ViolationCheckerRegistry.register(c2)
        ViolationCheckerRegistry.register(c3)
        assert len(ViolationCheckerRegistry.get_all()) == 3

    def test_clear_resets(self):
        from auditor.registry import ViolationCheckerRegistry
        ViolationCheckerRegistry.register({"name": "x"})
        ViolationCheckerRegistry.clear()
        assert len(ViolationCheckerRegistry.get_all()) == 0


class TestConditionEvaluatorRegistry:
    """Tests for ConditionEvaluatorRegistry."""

    def setup_method(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        ConditionEvaluatorRegistry.clear()
        # Re-register built-in evaluators
        from auditor.condition_registry import (
            _eval_path_prefix, _eval_class_suffix, _eval_class_contains,
            _eval_name_contains, _eval_calls_prefix
        )
        ConditionEvaluatorRegistry.register("path_prefix", _eval_path_prefix)
        ConditionEvaluatorRegistry.register("class_suffix", _eval_class_suffix)
        ConditionEvaluatorRegistry.register("class_contains", _eval_class_contains)
        ConditionEvaluatorRegistry.register("name_contains", _eval_name_contains)
        ConditionEvaluatorRegistry.register("calls_prefix", _eval_calls_prefix)

    def test_register_evaluator(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        ConditionEvaluatorRegistry.register("custom", lambda info, val: True)
        assert "custom" in ConditionEvaluatorRegistry.list_types()

    def test_evaluate_path_prefix(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        symbol = {"symbol": "foo", "filepath": "src/utils/helpers.py"}
        assert ConditionEvaluatorRegistry.evaluate("path_prefix", symbol, "src/utils/") is True
        assert ConditionEvaluatorRegistry.evaluate("path_prefix", symbol, "lib/") is False

    def test_evaluate_class_suffix(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        symbol = {"symbol": "MyClass", "filepath": "x.py"}
        assert ConditionEvaluatorRegistry.evaluate("class_suffix", symbol, "Class") is True
        assert ConditionEvaluatorRegistry.evaluate("class_suffix", symbol, "Service") is False

    def test_evaluate_class_contains(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        symbol = {"symbol": "MyServiceClass", "filepath": "x.py"}
        assert ConditionEvaluatorRegistry.evaluate("class_contains", symbol, "Service") is True
        assert ConditionEvaluatorRegistry.evaluate("class_contains", symbol, "Repository") is False

    def test_evaluate_name_contains(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        symbol = {"symbol": "handle_click_event", "filepath": "x.py"}
        assert ConditionEvaluatorRegistry.evaluate("name_contains", symbol, "click") is True
        assert ConditionEvaluatorRegistry.evaluate("name_contains", symbol, "hover") is False

    def test_evaluate_unknown_raises(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        with pytest.raises(ValueError, match="Unknown condition type"):
            ConditionEvaluatorRegistry.evaluate("nonexistent", {}, "val")

    def test_clear_resets(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        ConditionEvaluatorRegistry.register("temp", lambda info, val: True)
        ConditionEvaluatorRegistry.clear()
        assert len(ConditionEvaluatorRegistry.list_types()) == 0

    def test_list_types(self):
        from auditor.condition_registry import ConditionEvaluatorRegistry
        types = ConditionEvaluatorRegistry.list_types()
        assert "path_prefix" in types
        assert "class_suffix" in types
        assert "calls_prefix" in types
