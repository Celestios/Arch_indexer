"""
Tree-sitter AST structural metrics.
Calculates cyclomatic complexity, max nesting depth, and code line metrics.
"""
from typing import Dict, Any, Set
import tree_sitter


class MetricsCalculator:
    """Calculates structural metrics from AST nodes."""

    BRANCH_NODE_TYPES: Set[str] = {
        # Conditionals
        "if_statement", "elif_clause", "if_expression", "conditional_expression",
        # Loops
        "while_statement", "for_statement", "for_in_statement", "loop_expression",
        # Error handling
        "except_clause", "catch_clause",
        # Pattern matching / switch
        "match_arm", "case_clause", "switch_statement",
    }

    NESTING_NODE_TYPES: Set[str] = {
        "if_statement", "while_statement", "for_statement", "for_in_statement",
        "try_statement", "match_statement", "switch_statement", "with_statement",
        "loop_expression",
    }

    @classmethod
    def calculate_metrics(cls, node: tree_sitter.Node, code_bytes: bytes) -> Dict[str, Any]:
        """
        Calculates:
        - cyclomatic_complexity: int (minimum 1)
        - max_nesting_depth: int
        - loc: int
        """
        start_row = node.start_point.row
        end_row = node.end_point.row
        loc = max(1, end_row - start_row + 1)

        complexity = 1
        max_depth = 0

        # Traverse node subtree
        def traverse(curr: tree_sitter.Node, current_depth: int):
            nonlocal complexity, max_depth

            is_nesting = curr.type in cls.NESTING_NODE_TYPES
            next_depth = current_depth + 1 if is_nesting else current_depth
            if next_depth > max_depth:
                max_depth = next_depth

            if curr.type in cls.BRANCH_NODE_TYPES:
                complexity += 1
            elif curr.type == "boolean_operator":
                # Python boolean operator 'and' / 'or'
                for child in curr.children:
                    if child.type in ("and", "or"):
                        complexity += 1
            elif curr.type == "binary_expression":
                # C/Rust/JS '&&' / '||'
                op = curr.child_by_field_name("operator")
                if op:
                    op_text = code_bytes[op.start_byte:op.end_byte]
                    if op_text in (b"&&", b"||"):
                        complexity += 1

            for child in curr.children:
                traverse(child, next_depth)

        traverse(node, 0)

        return {
            "cyclomatic_complexity": complexity,
            "max_nesting_depth": max_depth,
            "loc": loc,
        }
