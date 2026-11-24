"""
Shared symbol reconciliation logic for unifying Tree-sitter AST declarations and SCIP symbols.
Ensures persistent symbol identity across incremental Tier 1 (AST) and Tier 2 (SCIP) indexing.
"""
import re
from typing import Dict, List, Optional, Tuple

from utils.helpers import demangle_scip_symbol
from utils.symbol_id import parse_canonical_id


def normalize_leaf(name: str) -> str:
    """Normalize a leaf symbol or path component for fuzzy comparison."""
    if not name:
        return ""
    leaf = re.split(r"[/:\\.#\s]", name.rstrip("()").replace("().", ""))[-1]
    return leaf.lower().replace("_", "")


def reconcile_symbol_id(
    clean_symbol: str,
    start_line: Optional[int],
    clean_to_existing: Dict[str, str],
    line_to_existing: Dict[int, str],
    occ_list: List[Tuple[str, int]],
    decl_name: Optional[str] = None
) -> Optional[str]:
    """
    Reconciles a candidate symbol against existing symbols and definition occurrences.
    Uses a canonical 3-tier matching heuristic:
      1. Exact clean_symbol match in existing symbols.
      2. Exact definition start_line match in existing definition occurrences.
      3. Fuzzy start_line window (+/- 2 lines) with normalized leaf name match.

    Returns:
      Matched existing symbol ID, or None if no match found.
    """
    # 1. Exact clean_symbol match
    if clean_symbol and clean_symbol in clean_to_existing:
        return clean_to_existing[clean_symbol]

    # 2. Exact definition start_line match
    if start_line is not None and start_line in line_to_existing:
        return line_to_existing[start_line]

    # 3. Fuzzy line match window (+/- 2 lines) with normalized leaf name match
    if start_line is not None and occ_list:
        target_leaf = normalize_leaf(decl_name) if decl_name else normalize_leaf(clean_symbol)
        if target_leaf:
            min_delta = 999
            best_match = None
            for sym_id, s_line in occ_list:
                delta = abs(start_line - s_line)
                if delta <= 2:
                    leaf_cand = parse_canonical_id(sym_id)[2] or demangle_scip_symbol(sym_id)
                    cand_leaf = normalize_leaf(leaf_cand)
                    if cand_leaf == target_leaf and delta < min_delta:
                        min_delta = delta
                        best_match = sym_id
            if best_match:
                return best_match

    return None
