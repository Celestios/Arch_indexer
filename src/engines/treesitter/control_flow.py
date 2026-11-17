"""
Tree-sitter AST control-flow context analysis.
Determines enclosing control structures for call sites and statements:
'[in loop]', '[in try/catch]', '[conditional]'.
"""
from typing import List, Optional
import tree_sitter


class ControlFlowAnalyzer:
    """Analyzes AST ancestry to determine control flow context tags."""

    LOOP_TYPES = {
        "for_statement", "while_statement", "for_in_statement", "loop_expression", "do_statement"
    }

    TRY_TYPES = {
        "try_statement", "except_clause", "catch_clause", "finally_clause"
    }

    CONDITIONAL_TYPES = {
        "if_statement", "elif_clause", "conditional_expression", "ternary_expression",
        "match_arm", "case_clause", "switch_statement"
    }

    @classmethod
    def get_context_tags(cls, node: tree_sitter.Node) -> List[str]:
        """Returns a list of tags describing the enclosing control structures."""
        tags = []
        has_loop = False
        has_try = False
        has_cond = False

        curr = node.parent
        # Stop if we hit a function or class boundary (context is function-local)
        stop_types = {
            "function_definition", "function_declaration", "function_item",
            "class_definition", "class_declaration", "module"
        }

        while curr is not None:
            if curr.type in stop_types:
                break

            if not has_loop and curr.type in cls.LOOP_TYPES:
                has_loop = True
                tags.append("[in loop]")

            if not has_try and curr.type in cls.TRY_TYPES:
                has_try = True
                tags.append("[in try/catch]")

            if not has_cond and curr.type in cls.CONDITIONAL_TYPES:
                has_cond = True
                tags.append("[conditional]")

            curr = curr.parent

        return tags

    @classmethod
    def format_context(cls, node: tree_sitter.Node) -> str:
        """Returns formatted context string like '[in loop][in try/catch]' or empty string."""
        tags = cls.get_context_tags(node)
        return "".join(tags)
