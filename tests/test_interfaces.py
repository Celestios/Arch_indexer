"""Tests for Protocol compliance across the codebase."""
import pytest
from pathlib import Path


class TestIndexerBackendProtocol:
    """Verify backend functions exist in engines.scip.wrapper."""

    def test_scip_wrapper_satisfies_protocol(self):
        import engines.scip.wrapper as wrapper
        assert hasattr(wrapper, 'detect_languages')
        assert hasattr(wrapper, 'run_indexer')



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
    """Verify ViolationChecker functions exist."""

    def test_dependency_checker_has_check(self):
        from auditor.violation_checkers.dependency import check
        assert callable(check)

    def test_naming_checker_has_check(self):
        from auditor.violation_checkers.naming import check
        assert callable(check)

    def test_pending_checker_has_check(self):
        from auditor.violation_checkers.pending import check
        assert callable(check)


class TestRepositoryInterfaces:
    """Verify repository domain store methods exist on concrete classes."""

    def test_graph_store_has_required_methods(self):
        from db.store_graph import GraphStore
        required = ['get_symbol', 'upsert_symbol', 'get_symbols_by_filepaths',
                    'get_occurrences_for_symbol', 'upsert_symbols_bulk',
                    'get_symbols_in_file', 'recalculate_connection_weights',
                    'get_all_symbols', 'add_edge', 'get_incoming_edges',
                    'get_outgoing_edges', 'delete_symbols_for_files', 'delete_edges_for_files']
        for method in required:
            assert hasattr(GraphStore, method), f"Missing: {method}"

    def test_workspace_store_has_required_methods(self):
        from db.store_workspace import WorkspaceStore
        required = ['upsert_file', 'get_file', 'upsert_files_bulk',
                    'update_file_manual_status', 'update_file_statuses',
                    'get_all_files_metadata', 'get_files_pending_audit_count',
                    'get_metadata', 'set_metadata', 'get_co_changes', 'record_co_changes']
        for method in required:
            assert hasattr(WorkspaceStore, method), f"Missing: {method}"

    def test_quality_store_has_required_methods(self):
        from db.store_quality import QualityStore
        required = ['upsert_rule', 'add_violation', 'get_violations',
                    'delete_violations',
                    'record_violations_bulk', 'get_diagnostics_for_file',
                    'record_diagnostics_bulk']
        for method in required:
            assert hasattr(QualityStore, method), f"Missing: {method}"

    def test_analytics_store_has_required_methods(self):
        from db.store_analytics import AnalyticsStore
        required = ['get_symbol_counts_by_kind', 'get_repo_totals',
                    'get_compliance_summary', 'get_transitive_closure']
        for method in required:
            assert hasattr(AnalyticsStore, method), f"Missing: {method}"

    def test_repository_composes_domain_stores(self):
        from unittest.mock import MagicMock
        from db.repository import Repository
        repo = Repository(db_conn=MagicMock())
        assert hasattr(repo, 'workspace')
        assert hasattr(repo, 'graph')
        assert hasattr(repo, 'quality')
        assert hasattr(repo, 'analytics')
        assert hasattr(repo, 'delete_files')
        assert hasattr(repo, 'delete_file')
        assert hasattr(repo, 'transaction')
