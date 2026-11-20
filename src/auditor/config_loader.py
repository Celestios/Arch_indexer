from pathlib import Path
from typing import Any, Dict, Optional, Union

from utils.arch_config import ArchConfig
from utils.helpers import load_config as _load_config


class ConfigLoader:
    """Handles loading and parsing of .arch/config.json configurations."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._cached_config: Optional[ArchConfig] = None

    def load_config(self) -> ArchConfig:
        """Loads and caches the normalized .arch/config.json configuration."""
        if self._cached_config is None:
            project_root = self.config_path.parent.parent
            self._cached_config = _load_config(project_root)
        return self._cached_config

    def get_applicable_config(
        self,
        filepath: str,
        config: Optional[Union[ArchConfig, Dict[str, Any]]] = None,
    ) -> Optional[Any]:
        """
        Resolves the most specific directory prefix configuration matching the filepath.
        Longest matching prefix wins. '.' is used for root-level files.

        Operates on ArchConfig.prefixes, so the top-level 'exclude' key is never
        treated as a prefix. A plain dict is still accepted for backwards
        compatibility.
        """
        if config is None:
            config = self.load_config()

        if isinstance(config, ArchConfig):
            prefixes = config.prefixes
        else:
            prefixes = config

        normalized_path = filepath.replace("\\", "/")
        matching_prefix = None
        for prefix in prefixes.keys():
            if prefix == ".":
                if matching_prefix is None:
                    matching_prefix = "."
            elif normalized_path.startswith(prefix):
                if matching_prefix is None or len(prefix) > len(matching_prefix):
                    matching_prefix = prefix
        return prefixes.get(matching_prefix) if matching_prefix else None
