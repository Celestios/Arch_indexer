from pathlib import Path
from typing import Dict, Any, Optional

from utils.helpers import load_config as _load_config


class ConfigLoader:
    """Handles loading and parsing of .arch/config.json configurations."""

    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load_config(self) -> Dict[str, Any]:
        """Loads and parses the .arch/config.json file."""
        project_root = self.config_path.parent.parent
        return _load_config(project_root)

    def get_applicable_config(self, filepath: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Resolves the most specific directory prefix configuration matching the filepath.
        Longest matching prefix wins. '.' is used for root-level files.
        """
        normalized_path = filepath.replace("\\", "/")
        matching_prefix = None
        for prefix in config.keys():
            if prefix == ".":
                if matching_prefix is None:
                    matching_prefix = "."
            elif normalized_path.startswith(prefix):
                if matching_prefix is None or len(prefix) > len(matching_prefix):
                    matching_prefix = prefix
        return config.get(matching_prefix) if matching_prefix else None
