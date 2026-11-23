"""Tests for Liskov Substitution Principle and Interface consistency."""
import pytest


class TestViolationCheckersConsistentInterface:
    """Verify all violation checkers have consistent check() interface."""

    def test_all_checkers_have_check_method(self):
        from auditor.violation_checkers.dependency import check as check_dep
        from auditor.violation_checkers.naming import check as check_nam
        from auditor.violation_checkers.pending import check as check_pen
        for checker_fn in [check_dep, check_nam, check_pen]:
            assert callable(checker_fn)
