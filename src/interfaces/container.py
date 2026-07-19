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
        self._embedder = None
        self._codeql_wrappers = {}
        self._dart_analyzer = None

    def _get_bin_dir(self) -> Path:
        """Resolve the bin directory for external tools."""
        try:
            from utils.progress import resolve_bin_dir
            return resolve_bin_dir()
        except Exception:
            return self.arch_dir / "bin"

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

    def get_embedder(self):
        """Get or create the LocalEmbedder."""
        if self._embedder is None:
            from engines.embedder import LocalEmbedder
            self._embedder = LocalEmbedder(self._get_bin_dir())
        return self._embedder

    def get_codeql_wrapper(self, language: str = "generic"):
        """Get or create a CodeQlWrapper for a specific language."""
        if language not in self._codeql_wrappers:
            from engines.codeql_wrapper import CodeQlWrapper
            self._codeql_wrappers[language] = CodeQlWrapper(self._get_bin_dir())
        return self._codeql_wrappers[language]

    def get_codeql_wrappers(self) -> dict:
        """Get a dict of all CodeQL wrappers keyed by language."""
        for lang in ["rust", "python", "go", "java", "generic"]:
            self.get_codeql_wrapper(lang)
        return self._codeql_wrappers.copy()

    def get_dart_analyzer(self):
        """Get or create the DartAnalyzerWrapper."""
        if self._dart_analyzer is None:
            from engines.dart_analyzer import DartAnalyzerWrapper
            self._dart_analyzer = DartAnalyzerWrapper(self.arch_dir)
        return self._dart_analyzer

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
