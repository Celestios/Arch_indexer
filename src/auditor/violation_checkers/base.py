from typing import Dict, List, Any, Optional, Protocol


class ViolationChecker(Protocol):
    """Protocol for violation checkers."""
    def check(self, repository, symbol_classifications: Dict, all_edges: List[Dict],
              config: Dict, filepath_filter: Optional[str],
              propagation_sources: Dict) -> List[Dict[str, Any]]: ...
