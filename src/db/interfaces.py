from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class DbConnectionInterface(Protocol):
    """Contract for database connections."""

    @abstractmethod
    @contextmanager
    def session(self) -> Iterator[Any]:
        """Context manager yielding a database connection."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Closes the database connection."""
        ...


@runtime_checkable
class FilesRepositoryInterface(Protocol):
    """Contract for file data access."""

    @abstractmethod
    def upsert_file(self, filepath: str, sha256: str, language: str) -> None: ...

    @abstractmethod
    def delete_file(self, filepath: str) -> None: ...

    @abstractmethod
    def get_file(self, filepath: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def upsert_files_bulk(self, files_list: List[Dict[str, Any]]) -> None: ...

    @abstractmethod
    def update_file_manual_status(self, filepath: str, status: str, justification: Optional[str] = None) -> None: ...

    @abstractmethod
    def update_file_manual_fields(self, filepath: str, manual_fields: dict, justification: Optional[str] = None) -> None: ...

    @abstractmethod
    def update_file_status(self, filepath: str, status: str) -> None: ...

    @abstractmethod
    def get_all_files_metadata(self) -> Dict[str, Dict[str, Any]]: ...

    @abstractmethod
    def clear_all_pending_audits(self, justification: str) -> None: ...

    @abstractmethod
    def get_files_pending_audit_count(self) -> int: ...


@runtime_checkable
class SymbolsRepositoryInterface(Protocol):
    """Contract for symbol data access."""

    @abstractmethod
    def upsert_symbol(
        self, symbol: str, filepath: Optional[str], kind: str,
        signature: Optional[str], docstring: Optional[str],
        body_hash: Optional[str],
        connection_weight: int = 0,
        parent_symbol: Optional[str] = None,
        clean_symbol: Optional[str] = None
    ) -> None: ...

    @abstractmethod
    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def get_symbols_by_filepaths(self, filepaths: List[str]) -> Dict[str, Dict[str, Any]]: ...

    @abstractmethod
    def add_occurrence(
        self, symbol: str, filepath: str, start_line: int,
        start_col: int, end_line: int, end_col: int, role: int
    ) -> None: ...

    @abstractmethod
    def get_occurrences_for_symbol(self, symbol: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def upsert_symbols_bulk(self, symbols_list: List[Dict[str, Any]], progress_callback=None) -> None: ...

    @abstractmethod
    def add_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]], progress_callback=None) -> None: ...

    @abstractmethod
    def get_symbols_in_file(self, filepath: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_symbols_metadata_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]: ...

    @abstractmethod
    def delete_symbols_for_file(self, filepath: str) -> None: ...

    @abstractmethod
    def delete_occurrences_for_file(self, filepath: str) -> None: ...

    @abstractmethod
    def delete_symbols_for_files(self, filepaths: List[str]) -> None: ...

    @abstractmethod
    def delete_occurrences_for_files(self, filepaths: List[str]) -> None: ...

    @abstractmethod
    def recalculate_connection_weights(self) -> None: ...

    @abstractmethod
    def add_diagnostics_bulk(self, diagnostics_list: List[Dict[str, Any]], progress_callback=None) -> None: ...

    @abstractmethod
    def delete_diagnostics_for_files(self, filepaths: List[str]) -> None: ...

    @abstractmethod
    def delete_diagnostics_for_file(self, filepath: str) -> None: ...

    @abstractmethod
    def get_diagnostics_for_file(self, filepath: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_diagnostics_for_symbol(self, symbol: str) -> List[Dict[str, Any]]: ...


@runtime_checkable
class EdgesRepositoryInterface(Protocol):
    """Contract for edge/relationship data access."""

    @abstractmethod
    def add_edge(self, source: str, target: str, relation: str, weight: float = 1.0) -> None: ...

    @abstractmethod
    def get_outgoing_edges(self, symbol: str) -> List[Dict[str, str]]: ...

    @abstractmethod
    def get_incoming_edges(self, symbol: str) -> List[Dict[str, str]]: ...

    @abstractmethod
    def add_edges_bulk(self, edges_list: List[Dict[str, Any]]) -> None: ...

    @abstractmethod
    def delete_edges_for_file(self, filepath: str) -> None: ...

    @abstractmethod
    def delete_edges_for_files(self, filepaths: List[str]) -> None: ...

    @abstractmethod
    def get_transitive_closure(self, symbol: str, max_depth: int = 3) -> Dict[str, List[Dict[str, Any]]]: ...

    @abstractmethod
    def get_dependent_files(self, filepaths: List[str]) -> List[str]: ...


@runtime_checkable
class ComplianceRepositoryInterface(Protocol):
    """Contract for compliance data access."""

    @abstractmethod
    def upsert_compliance_rule(self, rule_id: str, description: str, severity: str) -> None: ...

    @abstractmethod
    def add_violation(
        self, violation_id: str, rule_id: str, symbol: Optional[str],
        filepath: str, line: int, message: str, origin: str = "automatic"
    ) -> None: ...

    @abstractmethod
    def get_violations(self) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def delete_manual_violations(self, filepath: str) -> None: ...


@runtime_checkable
class MetricsRepositoryInterface(Protocol):
    """Contract for metrics data access."""

    @abstractmethod
    def get_symbol_counts_by_kind(self) -> Dict[str, int]: ...

    @abstractmethod
    def get_repo_totals(self) -> Dict[str, int]: ...

    @abstractmethod
    def get_symbols_by_file_prefix(self) -> Dict[str, int]: ...


@runtime_checkable
class RepositoryInterface(Protocol):
    """Contract for the repository facade composing all sub-repositories."""

    @property
    @abstractmethod
    def files(self) -> FilesRepositoryInterface: ...

    @property
    @abstractmethod
    def symbols(self) -> SymbolsRepositoryInterface: ...

    @property
    @abstractmethod
    def edges(self) -> EdgesRepositoryInterface: ...

    @property
    @abstractmethod
    def compliance(self) -> ComplianceRepositoryInterface: ...

    @property
    @abstractmethod
    def metrics(self) -> MetricsRepositoryInterface: ...
