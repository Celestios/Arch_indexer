"""Tree-sitter AST structural metrics."""
from typing import Dict, Any, Set
import tree_sitter

BRANCH_NODE_TYPES: Set[str] = {
    "if_statement", "elif_clause", "if_expression", "conditional_expression", "ternary_expression",
    "while_statement", "for_statement", "for_in_statement", "loop_expression",
    "for_expression", "while_expression",
    "except_clause", "catch_clause",
    "match_arm", "case_clause", "switch_case",
}

NESTING_NODE_TYPES: Set[str] = {
    "if_statement", "while_statement", "for_statement", "for_in_statement",
    "try_statement", "match_statement", "switch_statement", "with_statement",
    "loop_expression", "for_expression", "while_expression",
}


def calculate_metrics(node: tree_sitter.Node, code_bytes: bytes) -> Dict[str, Any]:
    """Calculates cyclomatic_complexity, max_nesting_depth, and loc for an AST node."""
    loc = max(1, node.end_point.row - node.start_point.row + 1)
    complexity = 1
    max_depth = 0

    def traverse(curr: tree_sitter.Node, current_depth: int):
        nonlocal complexity, max_depth
        next_depth = current_depth + 1 if curr.type in NESTING_NODE_TYPES else current_depth
        if next_depth > max_depth:
            max_depth = next_depth

        if curr.type in BRANCH_NODE_TYPES:
            complexity += 1
        elif curr.type == "boolean_operator":
            for child in curr.children:
                if child.type in ("and", "or"):
                    complexity += 1
        elif curr.type == "binary_expression":
            op = curr.child_by_field_name("operator")
            if op and code_bytes[op.start_byte:op.end_byte] in (b"&&", b"||"):
                complexity += 1

        for child in curr.children:
            traverse(child, next_depth)

    traverse(node, 0)
    return {"cyclomatic_complexity": complexity, "max_nesting_depth": max_depth, "loc": loc}
