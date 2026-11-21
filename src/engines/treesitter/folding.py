"""Tree-sitter skeleton code folding."""
from typing import Optional, List, Tuple, Union
import tree_sitter
from engines.registry import LanguageRegistry
from engines.treesitter.loader import get_parser

BODY_NODE_TYPES = {"block", "compound_statement", "statement_block", "field_declaration_list", "declaration_list"}
FUNCTION_NODE_TYPES = {
    "function_definition", "function_declaration", "function_item",
    "method_definition", "method_declaration", "arrow_function",
}


def _fold_body(
    body_node: tree_sitter.Node,
    lang: str,
    replacements: List[Tuple[int, int, str]],
):
    start_byte = body_node.start_byte
    end_byte = body_node.end_byte

    spec = LanguageRegistry.get_spec(lang)
    has_doc_stmt = bool(spec and spec.docstring_node_type == "expression_statement")

    doc_node: Optional[tree_sitter.Node] = None
    if has_doc_stmt and body_node.children:
        first_child = body_node.children[0]
        if first_child.type == "expression_statement" and first_child.children and first_child.children[0].type == "string":
            doc_node = first_child

    if doc_node:
        indent = " " * body_node.start_point.column
        replacements.append((doc_node.end_byte, end_byte, f"\n{indent}..."))
    elif has_doc_stmt:
        replacements.append((start_byte, end_byte, "..."))
    else:
        replacements.append((start_byte, end_byte, "{\n    ...\n}"))


def fold_code(source: Union[str, bytes], language: str) -> str:
    """Replaces function/method execution bodies with '...' while preserving signatures and docstrings."""
    code_bytes = source.encode("utf-8") if isinstance(source, str) else source
    parser = get_parser(language)
    if not parser:
        return code_bytes.decode("utf-8", errors="replace")

    tree = parser.parse(code_bytes)
    if not tree or not tree.root_node:
        return code_bytes.decode("utf-8", errors="replace")

    replacements: List[Tuple[int, int, str]] = []

    def visit(node: tree_sitter.Node):
        if node.type in FUNCTION_NODE_TYPES:
            body_node = node.child_by_field_name("body")
            if not body_node:
                for child in node.children:
                    if child.type in BODY_NODE_TYPES:
                        body_node = child
                        break
            if body_node and body_node.end_byte > body_node.start_byte:
                _fold_body(body_node, language.lower(), replacements)
                return
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    if not replacements:
        return code_bytes.decode("utf-8", errors="replace")

    replacements.sort(key=lambda r: r[0], reverse=True)
    res_bytes = bytearray(code_bytes)
    for start, end, repl in replacements:
        res_bytes[start:end] = repl.encode("utf-8")
    return res_bytes.decode("utf-8", errors="replace")
