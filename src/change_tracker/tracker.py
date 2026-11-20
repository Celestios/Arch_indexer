import hashlib
from pathlib import Path
from typing import Any

from utils.helpers import config_path_for


class ChangeTracker:
    """
    Handles hashing logic to track physical (file-level) and configuration (ontology) changes.
    """

    @staticmethod
    def calculate_sha256(filepath: Path) -> str:
        """Computes the SHA-256 hash of a file's content. Returns 'initial_hash' if unreadable."""
        if not filepath.exists() or not filepath.is_file():
            return "initial_hash"
        
        hasher = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return "initial_hash"

    @staticmethod
    def get_config_hash(project_root: Path) -> str:
        """Returns the current SHA-256 hash of .arch/config.json."""
        return ChangeTracker.calculate_sha256(config_path_for(project_root))

    @staticmethod
    def check_config_changed(project_root: Path, repository: Any) -> bool:
        """
        Compares the current hash of .arch/config.json with the one stored in system_metadata.
        """
        current_hash = ChangeTracker.get_config_hash(project_root)
        stored_hash = repository.workspace.get_metadata("config_hash")
        return stored_hash != current_hash

    @staticmethod
    def update_config_hash(project_root: Path, repository: Any):
        """
        Updates the stored hash of .arch/config.json in system_metadata to match the current file.
        """
        current_hash = ChangeTracker.get_config_hash(project_root)
        repository.workspace.set_metadata("config_hash", current_hash)
