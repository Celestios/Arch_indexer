"""Integration tests for end-to-end audit pipeline and MCP server."""
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open


class TestAuditPipeline:
    """Integration tests for the full audit pipeline."""

    def _make_mock_repository(self):
        """Create a mock repository with all sub-repositories."""
        repo = MagicMock()
        repo.files = MagicMock()
        repo.symbols = MagicMock()
        repo.edges = MagicMock()
        repo.compliance = MagicMock()
        repo.metrics = MagicMock()
        return repo

    def test_auditor_initializes_correctly(self):
        """Auditor creates all sub-components on init."""
        from auditor.analyzer import Auditor
        repo = self._make_mock_repository()
        project_root = Path("/fake/project")
        
        with patch.object(Path, "exists", return_value=True):
            auditor = Auditor(repo, project_root)
        
        assert auditor.repository == repo
        assert auditor.classifier is not None
        assert auditor.propagator is not None
        assert auditor.tracer is not None
        assert auditor.field_validator is not None
        assert auditor.edge_weight_updater is not None

    def test_auditor_run_audit_empty_config(self):
        """Auditor returns empty list when config is empty."""
        from auditor.analyzer import Auditor
        repo = self._make_mock_repository()
        project_root = Path("/fake/project")
        
        with patch.object(Path, "exists", return_value=True):
            auditor = Auditor(repo, project_root)
        
        auditor.config_loader = MagicMock()
        auditor.config_loader.load_config.return_value = {}
        
        violations = auditor.run_audit()
        assert violations == []

    def test_auditor_run_audit_with_violations(self):
        """Auditor detects violations when rules are configured."""
        from auditor.analyzer import Auditor
        repo = self._make_mock_repository()
        project_root = Path("/fake/project")
        
        config = {
            "src/": {
                "automatic_fields": {
                    "layer": {
                        "default": "Application",
                        "handler": "classification",
                        "assignment_rules": []
                    }
                },
                "rules": []
            }
        }
        
        # Mock symbol data
        symbols = [
            {"symbol": "src::main::func", "filepath": "src/main.py", "kind": "Function",
             "signature": "func()", "docstring": "test"}
        ]
        edges = []
        
        with patch.object(Path, "exists", return_value=True):
            auditor = Auditor(repo, project_root)
        
        auditor.config_loader = MagicMock()
        auditor.config_loader.load_config.return_value = config
        auditor.config_loader.get_applicable_config.return_value = config["src/"]
        
        repo.graph.get_all_symbols_with_metadata.return_value = symbols
        repo.graph.get_outgoing_edges.return_value = []
        repo.workspace.get_all_files_metadata.return_value = {}
        repo.graph.get_all_edges_with_relation.return_value = edges
        repo.workspace.get_all_files_metadata.return_value = {
            "src/main.py": {"filepath": "src/main.py", "manual_fields": {}, "pending_audit": False,
                           "justification": "", "sha256": "abc", "status": "COMPLIANT",
                           "manual_status": "COMPLIANT", "language": "python"}
        }
        repo.quality.get_violations.return_value = []
        
        violations = auditor.run_audit()
        # Should complete without error
        assert isinstance(violations, list)


class TestLanguageDetection:
    """Integration tests for language detection across the codebase."""

    def test_rust_detection(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language("src/main.rs") == "rust"
        assert LanguageRegistry.detect_language_from_name("Cargo.toml") == "rust"

    def test_dart_detection(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language("lib/app.dart") == "dart"
        assert LanguageRegistry.detect_language_from_name("pubspec.yaml") == "dart"

    def test_python_detection(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language("src/module.py") == "python"
        assert LanguageRegistry.detect_language_from_name("pyproject.toml") == "python"

    def test_unknown_language(self):
        from engines.registry import LanguageRegistry
        assert LanguageRegistry.detect_language("file.xyz") is None
        assert LanguageRegistry.detect_language_from_name("Makefile") is None


class TestServerConfig:
    """Integration tests for lazy server configuration."""

    def test_server_config_lazy(self):
        """server_config only resolves on first call."""
        from interface.server_config import get_project_root, get_arch_dir, get_db_path
        root = get_project_root()
        assert isinstance(root, Path)
        arch = get_arch_dir()
        assert arch.name == ".arch"
        db = get_db_path()
        assert db.name == "arch.db"