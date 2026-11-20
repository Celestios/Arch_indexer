from typing import List


class ViolationCheckerRegistry:
    """
    Registry for violation checkers. New checks added by registration.
    Maintained for test and extension compatibility.
    """

    _checkers: List = []

    @classmethod
    def register(cls, checker) -> None:
        """Register a violation checker instance."""
        cls._checkers.append(checker)

    @classmethod
    def get_all(cls) -> List:
        """Get all registered checkers in registration order."""
        return cls._checkers.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear all registered checkers (for testing)."""
        cls._checkers.clear()


def _register_defaults():
    try:
        from auditor.violation_checkers.dependency import DependencyViolationChecker
        from auditor.violation_checkers.naming import NamingViolationChecker
        from auditor.violation_checkers.pending import PendingAuditChecker
        ViolationCheckerRegistry.register(DependencyViolationChecker(repository=None, tracer=None, config_loader=None))
        ViolationCheckerRegistry.register(NamingViolationChecker(repository=None, tracer=None))
        ViolationCheckerRegistry.register(PendingAuditChecker(repository=None))
    except Exception:
        pass


_register_defaults()
