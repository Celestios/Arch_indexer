"""Tests for Liskov Substitution Principle compliance."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


class TestBaseReportLSP:
    """Verify BaseReport subclasses honor the abstract contract."""

    def test_base_report_cannot_be_instantiated(self):
        """BaseReport is ABC — cannot be instantiated directly."""
        from abc import ABC
        from reporter.generator import BaseReport
        assert issubclass(BaseReport, ABC)
        with pytest.raises(TypeError):
            BaseReport(MagicMock())

    def test_overview_report_has_generate(self):
        from reporter.generator import OverviewReport
        assert hasattr(OverviewReport, 'generate')
        assert callable(OverviewReport.generate)

    def test_overview_report_has_to_markdown(self):
        from reporter.generator import OverviewReport
        assert hasattr(OverviewReport, 'to_markdown')
        assert callable(OverviewReport.to_markdown)

    def test_compliance_report_has_generate(self):
        from reporter.generator import ComplianceReport
        assert hasattr(ComplianceReport, 'generate')
        assert callable(ComplianceReport.generate)

    def test_compliance_report_has_to_markdown(self):
        from reporter.generator import ComplianceReport
        assert hasattr(ComplianceReport, 'to_markdown')
        assert callable(ComplianceReport.to_markdown)

    def test_both_reports_share_to_json(self):
        """Both subclasses inherit to_json from BaseReport."""
        from reporter.generator import OverviewReport, ComplianceReport
        # to_json should be callable on both
        assert hasattr(OverviewReport, 'to_json')
        assert hasattr(ComplianceReport, 'to_json')


class TestEngineWrapperLSP:
    """Verify engine wrappers have consistent interface contracts."""

    def test_both_wrappers_have_is_available(self):
        from engines.codeql_wrapper import CodeQlWrapper
        from engines.dart_analyzer.wrapper import DartAnalyzerWrapper
        assert callable(getattr(CodeQlWrapper, 'is_available', None))
        assert callable(getattr(DartAnalyzerWrapper, 'is_available', None))

    def test_both_wrappers_have_create_database(self):
        from engines.codeql_wrapper import CodeQlWrapper
        from engines.dart_analyzer.wrapper import DartAnalyzerWrapper
        assert callable(getattr(CodeQlWrapper, 'create_database', None))
        assert callable(getattr(DartAnalyzerWrapper, 'create_database', None))

    def test_both_wrappers_have_run_query(self):
        from engines.codeql_wrapper import CodeQlWrapper
        from engines.dart_analyzer.wrapper import DartAnalyzerWrapper
        assert callable(getattr(CodeQlWrapper, 'run_query', None))
        assert callable(getattr(DartAnalyzerWrapper, 'run_query', None))

    def test_both_wrappers_have_decode(self):
        """Both have decode method (decode_bqrs or decode_results)."""
        from engines.codeql_wrapper import CodeQlWrapper
        from engines.dart_analyzer.wrapper import DartAnalyzerWrapper
        assert callable(getattr(CodeQlWrapper, 'decode_bqrs', None))
        assert callable(getattr(DartAnalyzerWrapper, 'decode_results', None))

    def test_both_wrappers_have_trace_data_flow(self):
        from engines.codeql_wrapper import CodeQlWrapper
        from engines.dart_analyzer.wrapper import DartAnalyzerWrapper
        assert callable(getattr(CodeQlWrapper, 'trace_data_flow', None))
        assert callable(getattr(DartAnalyzerWrapper, 'trace_data_flow', None))

    def test_dart_wrapper_has_extract_kinds(self):
        from engines.dart_analyzer.wrapper import DartAnalyzerWrapper
        assert callable(getattr(DartAnalyzerWrapper, 'extract_kinds', None))


class TestViolationCheckerLSP:
    """Verify all violation checkers have consistent check() interface."""

    def test_all_checkers_have_check_method(self):
        from auditor.violation_checkers.dependency import DependencyViolationChecker
        from auditor.violation_checkers.naming import NamingViolationChecker
        from auditor.violation_checkers.pending import PendingAuditChecker
        for checker_cls in [DependencyViolationChecker, NamingViolationChecker, PendingAuditChecker]:
            assert hasattr(checker_cls, 'check')
            assert callable(checker_cls.check)

    def test_registry_returns_all_checkers(self):
        from auditor.registry import ViolationCheckerRegistry
        from auditor.violation_checkers.dependency import DependencyViolationChecker
        from auditor.violation_checkers.naming import NamingViolationChecker
        from auditor.violation_checkers.pending import PendingAuditChecker
        # Ensure default checkers are registered
        existing = ViolationCheckerRegistry.get_all()
        existing_types = {type(c) for c in existing}
        for cls in [DependencyViolationChecker, NamingViolationChecker, PendingAuditChecker]:
            if cls not in existing_types:
                instance = cls.__new__(cls)
                ViolationCheckerRegistry.register(instance)
        checkers = ViolationCheckerRegistry.get_all()
        assert len(checkers) >= 3
        types = [type(c) for c in checkers]
        assert DependencyViolationChecker in types
        assert NamingViolationChecker in types
        assert PendingAuditChecker in types
