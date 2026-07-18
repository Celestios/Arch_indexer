import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigLoader:
    """Handles loading and parsing of .arch/config.json configurations."""

    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load_config(self) -> Dict[str, Any]:
        """Loads and parses the .arch/config.json file."""
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            return {}

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
