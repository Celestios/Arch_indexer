from pathlib import Path
from unittest.mock import patch
from utils.arch_config import ArchConfig
from utils.exclusions import (
    load_include_dirs,
    load_exclude_patterns,
    matches_glob,
    is_included,
    is_excluded,
    filter_paths
)


class TestLoadIncludeDirs:
    @patch("utils.exclusions.load_config")
    def test_empty_config_returns_none(self, mock_load):
        mock_load.return_value = None
        result = load_include_dirs(Path("/project"))
        assert result is None

    @patch("utils.exclusions.load_config")
    def test_none_config_returns_none(self, mock_load):
        mock_load.return_value = None
        result = load_include_dirs(Path("/project"))
        assert result is None

    @patch("utils.exclusions.load_config")
    def test_returns_dict_keys_as_set(self, mock_load):
        mock_load.return_value = ArchConfig.from_dict({"src/": {}, "lib/": {}})
        result = load_include_dirs(Path("/project"))
        assert result == {"src/", "lib/"}

    @patch("utils.exclusions.load_config")
    def test_non_dict_values_excluded(self, mock_load):
        mock_load.return_value = ArchConfig.from_dict({"src/": {}, "version": "1.0"})
        result = load_include_dirs(Path("/project"))
        assert result == {"src/"}

    @patch("utils.exclusions.load_config")
    def test_single_prefix(self, mock_load):
        mock_load.return_value = ArchConfig.from_dict({"my_code/": {"auto": True}})
        result = load_include_dirs(Path("/project"))
        assert result == {"my_code/"}


class TestIsIncluded:
    def test_exact_match(self):
        assert is_included("src/main.py", {"src/"}) is True

    def test_nested_path(self):
        assert is_included("src/core/db/connection.py", {"src/"}) is True

    def test_no_match(self):
        assert is_included("lib/other.py", {"src/"}) is False

    def test_multiple_include_dirs(self):
        assert is_included("lib/utils.py", {"src/", "lib/"}) is True

    def test_empty_include_dirs(self):
        assert is_included("src/main.py", set()) is False

    def test_deeply_nested(self):
        assert is_included("a/b/c/d/e.py", {"a/b/"}) is True


class TestFilterPaths:
    def test_none_include_dirs_yields_all(self, tmp_path):
        paths = [tmp_path / "a.py", tmp_path / "b.py"]
        result = list(filter_paths(paths, tmp_path, None))
        assert len(result) == 2

    def test_filters_by_include_dirs(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "lib").mkdir()
        src_file = tmp_path / "src" / "main.py"
        lib_file = tmp_path / "lib" / "other.py"
        result = list(filter_paths([src_file, lib_file], tmp_path, {"src/"}))
        assert src_file in result
        assert lib_file not in result

    def test_non_relative_paths_yielded(self, tmp_path):
        other_path = Path("C:/other/file.py")
        result = list(filter_paths([other_path], tmp_path, {"src/"}))
        assert other_path in result

    def test_empty_paths(self, tmp_path):
        result = list(filter_paths([], tmp_path, {"src/"}))
        assert result == []

    def test_all_filtered_out(self, tmp_path):
        (tmp_path / "src").mkdir()
        file = tmp_path / "src" / "main.py"
        result = list(filter_paths([file], tmp_path, {"lib/"}))
        assert result == []


class TestLoadExcludePatterns:
    @patch("utils.exclusions.load_config")
    def test_load_exclude_patterns_list(self, mock_load):
        mock_load.return_value = ArchConfig.from_dict({"exclude": ["lib/src/**", "**/tests/**"]})
        patterns = load_exclude_patterns(Path("/project"))
        assert patterns == ["lib/src/**", "**/tests/**"]

    @patch("utils.exclusions.load_config")
    def test_load_exclude_patterns_string(self, mock_load):
        mock_load.return_value = ArchConfig.from_dict({"exclude": "lib/src/**"})
        patterns = load_exclude_patterns(Path("/project"))
        assert patterns == ["lib/src/**"]

    @patch("utils.exclusions.load_config")
    def test_load_exclude_patterns_empty(self, mock_load):
        mock_load.return_value = ArchConfig.from_dict({})
        patterns = load_exclude_patterns(Path("/project"))
        assert patterns == []


class TestMatchesGlob:
    def test_glob_double_star(self):
        assert matches_glob("lib/src/domain/types.dart", "lib/src/**") is True
        assert matches_glob("lib/features/auth.dart", "lib/src/**") is False

    def test_glob_single_star(self):
        assert matches_glob("tests/test_foo.py", "tests/*") is True
        assert matches_glob("tests/sub/test_foo.py", "tests/*") is False

    def test_directory_prefix(self):
        assert matches_glob("lib/src/generated/code.dart", "lib/src") is True

    def test_file_pattern(self):
        assert matches_glob("src/app.test.js", "*.test.js") is True


class TestExclusionWithPatterns:
    def test_is_excluded_with_patterns(self):
        assert is_excluded("lib/src/service.dart", ["lib/src/**"]) is True
        assert is_excluded("lib/main.dart", ["lib/src/**"]) is False

    def test_is_included_respects_exclude_patterns(self):
        include_dirs = {"lib/"}
        exclude_pats = ["lib/src/**"]
        assert is_included("lib/features/auth.dart", include_dirs, exclude_pats) is True
        assert is_included("lib/src/internal.dart", include_dirs, exclude_pats) is False
