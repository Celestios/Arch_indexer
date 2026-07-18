from typing import List


class ViolationCheckerRegistry:
    """
    Registry for violation checkers. New checks added by registration.
    Replaces hardcoded checker sequence in Auditor.run_audit().
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
