import os
import sys
from pathlib import Path
from typing import Optional

from utils.helpers import CONFIG_DIR_NAME, config_path_for


class DependencyContainer:
    """
    Centralized dependency injection container.

    Replaces scattered wiring in main.py and server.py with a single
    composition root. Uses lazy initialization — components are only
    created when first accessed.

    Usage:
        container = DependencyContainer(project_root=Path("/my/project"))
        repository = container.get_repository()
        auditor = container.get_auditor()
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.arch_dir = project_root / CONFIG_DIR_NAME
        self.db_path = self.arch_dir / "arch.db"

        self._repository = None
        self._db_conn = None
        self._auditor = None

    def get_db_connection(self):
        """Get or create the database connection."""
        if self._db_conn is None:
            from db.connection import DbConnection
            if not self.db_path.exists():
                raise FileNotFoundError(
                    f"Arch database not found at {self.db_path}. "
                    "Please run 'arch init' first."
                )
            self._db_conn = DbConnection(self.db_path)
        return self._db_conn

    def get_repository(self):
        """Get or create the Repository (composed of sub-repositories)."""
        if self._repository is None:
            from db.repository import Repository
            db_conn = self.get_db_connection()
            self._repository = Repository(db_conn)
        return self._repository

    def get_auditor(self):
        """Get or create the Auditor with injected dependencies."""
        if self._auditor is None:
            from auditor.analyzer import Auditor
            repository = self.get_repository()
            self._auditor = Auditor(repository, self.project_root)
        return self._auditor

    def close(self):
        """Close the database connection and clean up resources."""
        if self._db_conn is not None:
            self._db_conn.close()
            self._db_conn = None
        self._repository = None
        self._auditor = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
