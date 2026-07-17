from typing import Set, List, Dict
from pathlib import Path


class TransitiveInvalidation:
    """
    When a file changes, find all files that depend on it and add them
    to the changed set for re-ingestion. This keeps reverse references accurate.

    Modeled after CKB v2's transitive invalidation approach.
    """

    def __init__(self, repository, max_depth: int = 2):
        self.repository = repository
        self.max_depth = max_depth

    def expand_changed_files(self, changed_files: List[str]) -> Set[str]:
        """
        Given a set of changed files, find all files that depend on them
        (transitively up to max_depth) and return the expanded set.
        """
        if not changed_files:
            return set()

        expanded = set(changed_files)
        queue = list(changed_files)
        visited = set(changed_files)

        for depth in range(self.max_depth):
            if not queue:
                break

            next_queue = []
            for filepath in queue:
                dependents = self._find_dependents(filepath)
                for dep in dependents:
                    if dep not in visited:
                        visited.add(dep)
                        expanded.add(dep)
                        next_queue.append(dep)

            queue = next_queue

        if len(expanded) > len(changed_files):
            print(f"[Invalidation] Expanded {len(changed_files)} changed files to {len(expanded)} (depth {self.max_depth})")

        return expanded

    def _find_dependents(self, filepath: str) -> List[str]:
        """
        Find files that import symbols defined in the given filepath.
        Uses the edges table to find reverse dependencies.
        """
        dependents = []

        # Find symbols defined in this file
        symbols_in_file = self.repository.symbols.get_symbols_in_file(filepath)
        if not symbols_in_file:
            return dependents

        symbol_list = [s["symbol"] for s in symbols_in_file]

        # Find files that reference these symbols (incoming edges)
        for symbol in symbol_list:
            incoming = self.repository.edges.get_incoming_edges(symbol)
            for edge in incoming:
                caller_sym = edge["source"]
                caller_info = self.repository.symbols.get_symbol(caller_sym)
                if caller_info and caller_info.get("filepath") and caller_info["filepath"] != filepath:
                    dependents.append(caller_info["filepath"])

        return dependents
