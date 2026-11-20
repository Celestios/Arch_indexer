"""Tests for shared DRY utilities."""
import pytest
from utils.helpers import (
    ViolationId, matches_filter, find_definition_line, ext_to_lang,
    IS_WINDOWS, config_path_for, load_config,
)
from pathlib import Path
from unittest.mock import MagicMock


class TestViolationId:
    def test_deterministic(self):
        id1 = ViolationId.generate("a", "b", "c")
        id2 = ViolationId.generate("a", "b", "c")
        assert id1 == id2

    def test_different_inputs(self):
        id1 = ViolationId.generate("a", "b")
        id2 = ViolationId.generate("a", "c")
        assert id1 != id2

    def test_length(self):
        assert len(ViolationId.generate("test")) == 16


class TestMatchesFilter:
    def test_no_filter(self):
        assert matches_filter("src/foo.py", None) is True

    def test_exact_match(self):
        assert matches_filter("src/foo.py", "src/") is True

    def test_no_match(self):
        assert matches_filter("lib/foo.py", "src/") is False

    def test_backslash_normalization(self):
        assert matches_filter("src\\foo.py", "src/") is True


class TestExtToLang:
    def test_rust(self):
        assert ext_to_lang(".rs") == "rust"

    def test_dart(self):
        assert ext_to_lang(".dart") == "dart"

    def test_unknown(self):
        assert ext_to_lang(".xyz") == "unknown"


class TestFindDefinitionLine:
    def test_finds_definition(self):
        repo = MagicMock()
        repo.graph.get_occurrences_for_symbol.return_value = [
            {"filepath": "foo.py", "start_line": 10, "role": 1},
            {"filepath": "foo.py", "start_line": 20, "role": 2},
        ]
        assert find_definition_line(repo, "sym", "foo.py") == 10

    def test_fallback_to_first(self):
        repo = MagicMock()
        repo.graph.get_occurrences_for_symbol.return_value = [
            {"filepath": "foo.py", "start_line": 5, "role": 2},
        ]
        assert find_definition_line(repo, "sym", "foo.py") == 5

    def test_no_occurrences(self):
        repo = MagicMock()
        repo.graph.get_occurrences_for_symbol.return_value = []
        assert find_definition_line(repo, "sym", "foo.py") == 1
