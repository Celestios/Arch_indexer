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



    """Verify all violation checkers have consistent check() interface."""

    def test_all_checkers_have_check_method(self):
        from auditor.violation_checkers.dependency import DependencyViolationChecker
        from auditor.violation_checkers.naming import NamingViolationChecker
        from auditor.violation_checkers.pending import PendingAuditChecker
        for checker_cls in [DependencyViolationChecker, NamingViolationChecker, PendingAuditChecker]:
            assert hasattr(checker_cls, 'check')
            assert callable(checker_cls.check)
