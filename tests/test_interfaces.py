"""Tests for Protocol compliance across the codebase."""
import pytest
from pathlib import Path


class TestIndexerBackendProtocol:
    """Verify IndexerBackend protocol is satisfied by ScipWrapper."""

    def test_scip_wrapper_satisfies_protocol(self):
        from engines.base import IndexerBackend
        from engines.scip_wrapper import ScipWrapper
        assert hasattr(ScipWrapper, 'detect_languages')
        assert hasattr(ScipWrapper, 'run_indexer')



class TestClassifierProtocol:
    """Verify ClassifierInterface protocol methods exist."""

    def test_symbol_classifier_has_methods(self):
        from auditor.classifier import SymbolClassifier
        assert hasattr(SymbolClassifier, 'evaluate_conditions')
        assert hasattr(SymbolClassifier, 'assign_automatic_fields')


class TestPropagatorProtocol:
    """Verify PropagatorInterface protocol methods exist."""

    def test_metadata_propagator_has_methods(self):
        from auditor.propagation import MetadataPropagator
        assert hasattr(MetadataPropagator, 'run_propagation')


class TestPathTracerProtocol:
    """Verify PathTracerInterface protocol methods exist."""

    def test_path_tracer_has_methods(self):
        from auditor.path_tracer import PathTracer
        assert hasattr(PathTracer, 'format_path_trace')
        assert hasattr(PathTracer, 'matches_blocklist')
        assert hasattr(PathTracer, 'get_simple_name')


class TestViolationCheckerProtocol:
    """Verify ViolationChecker protocol methods exist."""

    def test_dependency_checker_has_check(self):
        from auditor.violation_checkers.dependency import DependencyViolationChecker
        assert hasattr(DependencyViolationChecker, 'check')

    def test_naming_checker_has_check(self):
        from auditor.violation_checkers.naming import NamingViolationChecker
        assert hasattr(NamingViolationChecker, 'check')

    def test_pending_checker_has_check(self):
        from auditor.violation_checkers.pending import PendingAuditChecker
        assert hasattr(PendingAuditChecker, 'check')


class TestRepositoryInterfaces:
    """Verify repository interface methods exist on concrete classes."""

    def test_symbols_repository_has_required_methods(self):
        from db.repository_symbols import SymbolsRepository
        required = ['get_symbol', 'upsert_symbol', 'get_symbols_by_filepaths',
                     'get_occurrences_for_symbol', 'upsert_symbols_bulk',
                     'get_symbols_in_file',
                     'delete_symbols_for_file', 'delete_occurrences_for_file',
                     'recalculate_connection_weights', 'get_all_symbols',
                     'get_all_symbols_with_metadata']
        for method in required:
            assert hasattr(SymbolsRepository, method), f"Missing: {method}"

    def test_files_repository_has_required_methods(self):
        from db.repository_files import FilesRepository
        required = ['upsert_file', 'delete_file', 'get_file',
                     'upsert_files_bulk', 'update_file_manual_status',
                     'update_file_status', 'get_all_files_metadata',
                     'get_files_pending_audit_count']
        for method in required:
            assert hasattr(FilesRepository, method), f"Missing: {method}"

    def test_edges_repository_has_required_methods(self):
        from db.repository_edges import EdgesRepository
        required = ['add_edge', 'get_outgoing_edges', 'get_incoming_edges',
                     'add_edges_bulk', 'delete_edges_for_file',
                     'get_transitive_closure', 'get_all_edges']
        for method in required:
            assert hasattr(EdgesRepository, method), f"Missing: {method}"

    def test_compliance_repository_has_required_methods(self):
        from db.repository_compliance import ComplianceRepository
        required = ['upsert_compliance_rule', 'add_violation',
                     'get_violations', 'delete_manual_violations',
                     'delete_automatic_violations', 'upsert_violations_bulk']
        for method in required:
            assert hasattr(ComplianceRepository, method), f"Missing: {method}"

    def test_metrics_repository_has_required_methods(self):
        from db.repository_metrics import MetricsRepository
        required = ['get_symbol_counts_by_kind', 'get_repo_totals',
                     'get_symbols_by_file_prefix']
        for method in required:
            assert hasattr(MetricsRepository, method), f"Missing: {method}"

    def test_repository_composes_sub_repositories(self):
        from unittest.mock import MagicMock
        from db.repository import Repository
        repo = Repository(db_conn=MagicMock())
        assert hasattr(repo, 'files')
        assert hasattr(repo, 'symbols')
        assert hasattr(repo, 'edges')
        assert hasattr(repo, 'compliance')
        assert hasattr(repo, 'metrics')
