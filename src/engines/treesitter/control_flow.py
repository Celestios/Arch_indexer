"""Tree-sitter AST control-flow context analysis."""
from typing import List
import tree_sitter

LOOP_TYPES = {"for_statement", "while_statement", "for_in_statement", "loop_expression", "do_statement"}
TRY_TYPES = {"try_statement", "except_clause", "catch_clause", "finally_clause"}
CONDITIONAL_TYPES = {
    "if_statement", "elif_clause", "conditional_expression", "ternary_expression",
    "match_arm", "case_clause", "switch_statement",
}
_STOP_TYPES = {
    "function_definition", "function_declaration", "function_item",
    "class_definition", "class_declaration", "module",
}


def get_context_tags(node: tree_sitter.Node) -> List[str]:
    """Returns a list of tags describing the enclosing control structures."""
    tags = []
    has_loop = has_try = has_cond = False
    curr = node.parent

    while curr is not None:
        if curr.type in _STOP_TYPES:
            break
        if not has_loop and curr.type in LOOP_TYPES:
            has_loop = True
            tags.append("[in loop]")
        if not has_try and curr.type in TRY_TYPES:
            has_try = True
            tags.append("[in try/catch]")
        if not has_cond and curr.type in CONDITIONAL_TYPES:
            has_cond = True
            tags.append("[conditional]")
        curr = curr.parent

    return tags


def format_context(node: tree_sitter.Node) -> str:
    """Returns formatted context string like '[in loop][in try/catch]'."""
    return "".join(get_context_tags(node))
