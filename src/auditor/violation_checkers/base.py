from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from db.repository import Repository

if TYPE_CHECKING:
    from auditor.snapshot import AuditSnapshot


class BaseViolationChecker(ABC):
    """Abstract base class for architectural violation checkers."""

    def __init__(self, repository: Optional[Repository] = None):
        self.repository = repository

    @abstractmethod
    def check(
        self,
        snapshot: Any,
        symbol_classifications: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        filepath_filter: Optional[str] = None,
        propagation_sources: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Evaluate architectural compliance rules and return detected violations."""
        pass
