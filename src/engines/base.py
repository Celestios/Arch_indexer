from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any, Protocol, runtime_checkable


@runtime_checkable
class IndexerBackend(Protocol):
    """
    Contract for indexers that produce SCIP/LSIF code navigation indices.
    """

    @abstractmethod
    def detect_languages(self, project_root: Path) -> List[str]:
        """
        Detects which languages are present in the project.
        """
        ...

    @abstractmethod
    def run_indexer(
        self,
        project_root: Path,
        language: str
    ) -> Optional[Path]:
        """
        Runs the SCIP indexer for a specific language.
        """
        ...
