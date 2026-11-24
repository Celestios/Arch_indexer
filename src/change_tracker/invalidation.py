import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def expand_changed_files(
    repository,
    changed_files: List[str],
    new_symbols: Optional[Dict[str, Dict[str, Any]]] = None,
    max_depth: int = 1,
) -> Set[str]:
    """
    Expands changed_files to include dependent files (up to max_depth).
    Only invalidates callers of files whose exported symbol IDs or signatures changed.
    new_symbols must map canonical symbol_id -> symbol record dict (containing filepath and signature).
    """
    if not changed_files:
        return set()

    expanded = set(changed_files)

    files_to_check: List[str] = []
    if new_symbols is not None:
        new_by_file: Dict[str, Dict[str, Optional[str]]] = {}
        for sym_id, sym_rec in new_symbols.items():
            fp = sym_rec.get("filepath")
            if fp:
                fp_norm = fp.replace("\\", "/")
                new_by_file.setdefault(fp_norm, {})[sym_rec.get("symbol", sym_id)] = sym_rec.get("signature")

        all_norm_fps = [fp.replace("\\", "/") for fp in changed_files]
        all_old_syms = repository.graph.get_symbols_for_files(all_norm_fps)
        old_syms_by_file: Dict[str, Dict[str, Optional[str]]] = {}
        for s in all_old_syms:
            fp = (s.get("filepath") or "").replace("\\", "/")
            old_syms_by_file.setdefault(fp, {})[s["symbol"]] = s.get("signature")

        for fp in changed_files:
            fp_norm = fp.replace("\\", "/")
            old_map = old_syms_by_file.get(fp_norm, {})
            new_map = new_by_file.get(fp_norm, {})
            if set(old_map.keys()) != set(new_map.keys()) or any(old_map[s] != new_map[s] for s in old_map):
                files_to_check.append(fp)
    else:
        files_to_check = list(changed_files)

    if not files_to_check:
        return expanded

    queue = list(files_to_check)
    visited = set(changed_files)

    for _ in range(max_depth):
        if not queue:
            break
        dependents = repository.graph.get_dependent_files(queue)
        next_queue = []
        for dep in dependents:
            if dep not in visited:
                visited.add(dep)
                expanded.add(dep)
                next_queue.append(dep)
        queue = next_queue

    if len(expanded) > len(changed_files):
        logger.info("[Invalidation] Expanded %d changed files to %d (depth %d)", len(changed_files), len(expanded), max_depth)

    return expanded
