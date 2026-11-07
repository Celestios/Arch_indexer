from pathlib import Path
from unittest.mock import patch
from auditor.config_loader import ConfigLoader


class TestConfigLoader:
    def test_load_config_delegates_to_helpers(self, tmp_path):
        config_path = tmp_path / ".arch" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('{"src/": {}}')
        loader = ConfigLoader(config_path)
        with patch("auditor.config_loader._load_config") as mock_load:
            mock_load.return_value = {"src/": {}}
            result = loader.load_config()
            mock_load.assert_called_once_with(tmp_path)
            assert result == {"src/": {}}

    def test_get_applicable_config_exact_prefix(self):
        config = {
            "src/core/": {"layer": "core"},
            "src/": {"layer": "app"},
        }
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("src/core/utils.py", config)
        assert result == {"layer": "core"}

    def test_get_applicable_config_longest_prefix_wins(self):
        config = {
            "src/": {"layer": "app"},
            "src/core/": {"layer": "core"},
            "src/core/db/": {"layer": "db"},
        }
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("src/core/db/connection.py", config)
        assert result == {"layer": "db"}

    def test_get_applicable_config_root_fallback(self):
        config = {
            ".": {"layer": "root"},
            "src/": {"layer": "app"},
        }
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("README.md", config)
        assert result == {"layer": "root"}

    def test_get_applicable_config_no_match(self):
        config = {
            "src/": {"layer": "app"},
        }
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("lib/other.py", config)
        assert result is None

    def test_get_applicable_config_backslash_normalized(self):
        config = {
            "src/core/": {"layer": "core"},
        }
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("src\\core\\utils.py", config)
        assert result == {"layer": "core"}

    def test_get_applicable_config_dot_only(self):
        config = {".": {"layer": "root"}}
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("anything.py", config)
        assert result == {"layer": "root"}

    def test_get_applicable_config_empty_config(self):
        loader = ConfigLoader(Path("/fake/.arch/config.json"))
        result = loader.get_applicable_config("src/file.py", {})
        assert result is None
