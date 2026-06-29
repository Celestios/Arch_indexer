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

        with self.repository.db_conn.session() as conn:
            # Find symbols defined in this file
            symbols_in_file = conn.execute(
                "SELECT symbol FROM symbols WHERE filepath = ?", (filepath,)
            ).fetchall()

            if not symbols_in_file:
                return dependents

            symbol_list = [r[0] for r in symbols_in_file]

            # Find files that reference these symbols (incoming edges)
            for symbol in symbol_list:
                callers = conn.execute(
                    "SELECT DISTINCT source FROM edges WHERE target = ?", (symbol,)
                ).fetchall()

                for (caller_sym,) in callers:
                    # Get the filepath of the caller
                    caller_file = conn.execute(
                        "SELECT filepath FROM symbols WHERE symbol = ?", (caller_sym,)
                    ).fetchone()

                    if caller_file and caller_file[0] and caller_file[0] != filepath:
                        dependents.append(caller_file[0])

        return dependents
