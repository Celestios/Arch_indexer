"""
Tree-sitter skeleton code folding.
Folds implementation bodies to '...' while strictly preserving signatures, docstrings,
decorators, and type definitions.
"""
from typing import Optional, List, Tuple
import tree_sitter
from engines.registry import LanguageRegistry
from engines.treesitter.loader import get_parser


class CodeFolder:
    """Provides skeleton folding for source files across languages."""

    BODY_NODE_TYPES = {
        "block", "compound_statement", "statement_block", "field_declaration_list", "declaration_list"
    }

    FUNCTION_NODE_TYPES = {
        "function_definition", "function_declaration", "function_item", "method_definition",
        "method_declaration", "arrow_function",
    }

    @classmethod
    def fold_code(cls, source: str | bytes, language: str) -> str:
        """
        Parses the code and replaces function/method execution bodies with '...'.
        Preserves docstrings at the start of bodies.
        """
        if isinstance(source, str):
            code_bytes = source.encode("utf-8")
        else:
            code_bytes = source

        parser = get_parser(language)
        if not parser:
            return code_bytes.decode("utf-8", errors="replace")

        tree = parser.parse(code_bytes)
        if not tree or not tree.root_node:
            return code_bytes.decode("utf-8", errors="replace")

        # Collect byte replacements: list of (start_byte, end_byte, replacement_str)
        replacements: List[Tuple[int, int, str]] = []

        def visit(node: tree_sitter.Node):
            if node.type in cls.FUNCTION_NODE_TYPES:
                body_node = node.child_by_field_name("body")
                if not body_node:
                    for child in node.children:
                        if child.type in cls.BODY_NODE_TYPES:
                            body_node = child
                            break

                if body_node and body_node.end_byte > body_node.start_byte:
                    cls._fold_body(body_node, code_bytes, language.lower(), replacements)
                    return  # Do not recurse into folded body

            for child in node.children:
                visit(child)

        visit(tree.root_node)

        if not replacements:
            return code_bytes.decode("utf-8", errors="replace")

        # Sort replacements in reverse order of start_byte to apply from bottom to top
        replacements.sort(key=lambda r: r[0], reverse=True)

        res_bytes = bytearray(code_bytes)
        for start, end, repl in replacements:
            res_bytes[start:end] = repl.encode("utf-8")

        return res_bytes.decode("utf-8", errors="replace")

    @classmethod
    def _fold_body(
        cls,
        body_node: tree_sitter.Node,
        code_bytes: bytes,
        lang: str,
        replacements: List[Tuple[int, int, str]],
    ):
        start_byte = body_node.start_byte
        end_byte = body_node.end_byte

        # Check for initial docstring
        doc_node: Optional[tree_sitter.Node] = None
        spec = LanguageRegistry.get_spec(lang)
        has_doc_stmt = bool(spec and spec.docstring_node_type == "expression_statement")

        if has_doc_stmt and body_node.children:
            first_child = body_node.children[0]
            if first_child.type == "expression_statement" and first_child.children:
                if first_child.children[0].type == "string":
                    doc_node = first_child

        if doc_node:
            # Replace everything from end of docstring statement to end of body
            repl_start = doc_node.end_byte
            indent = " " * (body_node.start_point.column)
            # Find remaining text
            repl = f"\n{indent}..."
            replacements.append((repl_start, end_byte, repl))
        else:
            if has_doc_stmt:
                # In block-based languages without braces, body_node starts after the newline and indentation
                repl = "..."
                replacements.append((start_byte, end_byte, repl))
            else:
                # C-style braces: { ... }
                repl = "{\n    ...\n}"
                replacements.append((start_byte, end_byte, repl))
