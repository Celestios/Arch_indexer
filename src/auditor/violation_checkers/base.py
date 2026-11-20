from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from db.repository import Repository

if TYPE_CHECKING:
    from auditor.snapshot import AuditSnapshot


class BaseViolationChecker(ABC):
    """Abstract base class for architectural violation checkers."""

    def __init__(self, repository: Repository):
        self.repository = repository

    @abstractmethod
    def check(
        self,
        symbol_classifications: Dict,
        all_edges: Optional[List[Dict]] = None,
        config: Optional[Dict] = None,
        filepath_filter: Optional[str] = None,
        propagation_sources: Optional[Dict] = None,
        snapshot: Optional["AuditSnapshot"] = None
    ) -> List[Dict[str, Any]]:
        """Evaluate architectural compliance rules and return detected violations."""
        pass
