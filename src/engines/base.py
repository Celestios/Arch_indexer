from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any, Protocol, runtime_checkable


@runtime_checkable
class LanguageBackend(Protocol):
    """
    Language-agnostic contract for all analysis backends.
    
    Each language (Rust, Dart, Python) should have a class implementing this protocol.
    The protocol is runtime_checkable so isinstance() checks work.
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if this backend's tooling is installed and functional."""
        ...

    @abstractmethod
    def create_database(
        self,
        source_root: Path,
        db_output_dir: Path,
        language: str,
        **kwargs: Any
    ) -> bool:
        """
        Creates an analysis database for the given language.
        
        Args:
            source_root: Root directory of the source code
            db_output_dir: Where to store the database
            language: Language identifier (e.g., "rust", "dart", "python")
            **kwargs: Language-specific options (e.g., force=True)
            
        Returns:
            True if database was created successfully
        """
        ...


@runtime_checkable
class QueryEngine(Protocol):
    """
    Contract for engines that execute semantic queries against a database.
    
    Used by CodeQlWrapper and DartAnalyzerWrapper for running .ql queries
    and decoding results.
    """

    @abstractmethod
    def run_query(
        self,
        db_dir: Path,
        ql_file: Path,
        bqrs_output: Path
    ) -> bool:
        """
        Executes a query against the database.
        
        Args:
            db_dir: Path to the database directory
            ql_file: Path to the query file (.ql)
            bqrs_output: Path where binary results should be written
            
        Returns:
            True if query executed successfully
        """
        ...

    @abstractmethod
    def decode_bqrs(
        self,
        bqrs_file: Path,
        json_output: Path
    ) -> Optional[Dict[str, Any]]:
        """
        Decodes binary query results into JSON format.
        
        Args:
            bqrs_file: Path to binary results file
            json_output: Path where JSON should be written
            
        Returns:
            Decoded results dict, or None on failure
        """
        ...


@runtime_checkable
class DataFlowTracer(Protocol):
    """
    Contract for engines that trace data flow between symbols.
    """

    @abstractmethod
    def trace_data_flow(
        self,
        db_dir: Path,
        source_symbol: str,
        sink_symbol: str,
        language: str = "rust"
    ) -> List[Dict[str, Any]]:
        """
        Traces data flow from source_symbol to sink_symbol.
        
        Args:
            db_dir: Path to the database directory
            source_symbol: Fully qualified source symbol
            sink_symbol: Fully qualified sink symbol
            language: Language identifier
            
        Returns:
            List of flow steps, each with keys: symbol, filepath, line, col, type
        """
        ...


@runtime_checkable
class IndexerBackend(Protocol):
    """
    Contract for indexers that produce SCIP/LSIF code navigation indices.
    """

    @abstractmethod
    def detect_languages(self, project_root: Path) -> List[str]:
        """
        Detects which languages are present in the project.
        
        Args:
            project_root: Root directory of the project
            
        Returns:
            List of language identifiers found (e.g., ["rust", "dart"])
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
        
        Args:
            project_root: Root directory of the project
            language: Language to index
            
        Returns:
            Path to generated index.scip, or None on failure
        """
        ...


@runtime_checkable
class EmbedderInterface(Protocol):
    """
    Contract for text embedding backends.
    Used for semantic search over code symbols.
    """

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """
        Generates a normalized vector embedding for the input text.
        
        Args:
            text: Input text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        ...


@runtime_checkable
class FfiDetector(Protocol):
    """
    Contract for FFI surface detection per language.
    Each language can have its own FFI detection strategy.
    """

    @abstractmethod
    def detect(self, project_root: Path) -> List[Any]:
        """
        Detects FFI entry points in the project.
        
        Args:
            project_root: Root directory of the project
            
        Returns:
            List of FfiSurface objects (or compatible dataclass instances)
        """
        ...
