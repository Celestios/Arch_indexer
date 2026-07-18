from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class ClassifierInterface(Protocol):
    """
    Contract for symbol classification engines.
    Evaluates conditions against symbols and assigns automatic fields.
    """

    @abstractmethod
    def evaluate_conditions(
        self,
        symbol_info: Dict[str, Any],
        conditions: Dict[str, Any],
        outgoing_targets: List[str]
    ) -> bool:
        """
        Returns True if a symbol definition meets all the specified assignment conditions.
        
        Args:
            symbol_info: Symbol metadata (symbol, filepath, kind, signature, etc.)
            conditions: Condition dict with keys like path_prefix, class_suffix, etc.
            outgoing_targets: List of symbols this symbol calls
            
        Returns:
            True if all conditions are satisfied
        """
        ...

    @abstractmethod
    def assign_automatic_fields(
        self,
        symbol_info: Dict[str, Any],
        prefix_conf: Dict[str, Any],
        outgoing_targets: List[str]
    ) -> Dict[str, Any]:
        """
        Evaluates the prefix configuration's automatic fields and returns assigned values.
        
        Args:
            symbol_info: Symbol metadata
            prefix_conf: Configuration dict with automatic_fields and assignment_rules
            outgoing_targets: List of symbols this symbol calls
            
        Returns:
            Dict mapping field names to assigned values
        """
        ...


@runtime_checkable
class PropagatorInterface(Protocol):
    """
    Contract for metadata propagation on call graphs.
    Propagates symbol metadata downstream or upstream using worklist algorithms.
    """

    @abstractmethod
    def run_propagation(
        self,
        symbol_classifications: Dict[str, Dict[str, Any]],
        all_edges: List[Dict[str, Any]],
        config: Dict[str, Any]
    ) -> Dict[tuple, str]:
        """
        Runs the fixed-point worklist propagation algorithm on the call graph.
        
        Args:
            symbol_classifications: {symbol: {"fields": {field_name: value}}}
            all_edges: List of {"source": str, "target": str, ...} dicts
            config: Full config with automatic_fields containing propagation settings
            
        Returns:
            Predecessor mapping (child, field_name) -> parent symbol
        """
        ...


@runtime_checkable
class PathTracerInterface(Protocol):
    """
    Contract for violation path tracing and formatting.
    """

    @abstractmethod
    def get_simple_name(self, symbol: str) -> str:
        """
        Extracts the simple class or function name from a SCIP FQN.
        
        Args:
            symbol: Full SCIP-qualified symbol name
            
        Returns:
            Simple name (last segment after separator)
        """
        ...

    @abstractmethod
    def format_path_trace(self, path: List[str]) -> str:
        """
        Generates a formatted, line-numbered path trace from source to target.
        
        Args:
            path: Ordered list of symbols from source to target
            
        Returns:
            Formatted string with numbered path entries
        """
        ...

    @abstractmethod
    def matches_blocklist(self, symbol: str, blocklist: List[str]) -> bool:
        """
        Checks if a symbol matches any pattern in a blocklist.
        
        Args:
            symbol: Symbol to check
            blocklist: List of glob patterns (e.g., ["std::*", "libc::*"])
            
        Returns:
            True if symbol matches any blocklist pattern
        """
        ...


@runtime_checkable
class ViolationCheckerInterface(Protocol):
    """
    Contract for individual violation checkers.
    Each checker examines one type of violation (dependency, naming, etc.).
    """

    @abstractmethod
    def check(
        self,
        repository: Any,
        config: Dict[str, Any],
        symbol_classifications: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Runs a specific violation check and returns found violations.
        
        Args:
            repository: Repository instance for database access
            config: The applicable prefix configuration
            symbol_classifications: Current symbol classifications with fields
            
        Returns:
            List of violation dicts with keys: rule_id, symbol, filepath, message, etc.
        """
        ...
