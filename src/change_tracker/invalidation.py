from typing import Set, List, Dict, Optional, Any
from pathlib import Path


class TransitiveInvalidation:
    """
    When a file changes, find all files that depend on it and add them
    to the changed set for re-ingestion if exported symbol IDs or signatures changed.
    Uses a single SQL join query and max_depth=1.
    """

    def __init__(self, repository, max_depth: int = 1):
        self.repository = repository
        self.max_depth = max_depth

    def expand_changed_files(
        self,
        changed_files: List[str],
        new_symbols: Optional[Any] = None
    ) -> Set[str]:
        """
        Given a set of changed files, find all files that depend on them
        (up to max_depth, defaulting to 1) and return the expanded set.
        Only triggers invalidation for files whose exported symbol IDs or signatures changed.
        """
        if not changed_files:
            return set()

        expanded = set(changed_files)

        # Determine which files actually had interface (symbol ID or signature) changes
        files_to_check = []
        if new_symbols is not None:
            new_by_file: Dict[str, Dict[str, Optional[str]]] = {}
            if isinstance(new_symbols, dict):
                for k, v in new_symbols.items():
                    if isinstance(v, dict) and "filepath" in v:
                        fp = v.get("filepath")
                        if fp:
                            new_by_file.setdefault(fp, {})[v.get("symbol", k)] = v.get("signature")
                    elif isinstance(v, dict):
                        new_by_file[k] = v
            elif isinstance(new_symbols, (list, set, tuple)):
                for s in new_symbols:
                    if isinstance(s, dict):
                        fp = s.get("filepath")
                        if fp:
                            new_by_file.setdefault(fp, {})[s.get("symbol")] = s.get("signature")

            for fp in changed_files:
                old_syms = self.repository.symbols.get_symbols_in_file(fp)
                old_map = {s["symbol"]: s.get("signature") for s in old_syms}
                new_map = new_by_file.get(fp, {})

                # If symbol set or any signature changed, we must invalidate callers
                if set(old_map.keys()) != set(new_map.keys()) or any(old_map[s] != new_map[s] for s in old_map):
                    files_to_check.append(fp)
        else:
            files_to_check = list(changed_files)

        if not files_to_check:
            return expanded

        queue = list(files_to_check)
        visited = set(changed_files)

        for _ in range(self.max_depth):
            if not queue:
                break
            # Single join query to get callers of symbols in queue
            dependents = self.repository.edges.get_dependent_files(queue)
            next_queue = []
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
        Legacy/helper method: find files that import symbols defined in the given filepath.
        Uses single join query for efficiency.
        """
        return self.repository.edges.get_dependent_files([filepath])
