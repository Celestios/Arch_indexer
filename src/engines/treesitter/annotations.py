"""
Tree-sitter AST annotation and attribute extraction.
Extracts decorators, attributes, visibility modifiers, and compiler tags from declaration nodes.
"""
from typing import List, Dict, Any, Optional
import tree_sitter


class AnnotationExtractor:
    """Extracts decorators, attributes, and visibility modifiers from AST nodes."""

    _DISPATCH_TABLE = {
        "python": "_extract_python",
        "rust": "_extract_rust",
        "typescript": "_extract_typescript",
        "tsx": "_extract_typescript",
        "javascript": "_extract_typescript",
        "js": "_extract_typescript",
        "go": "_extract_go",
        "java": "_extract_csharp_java",
        "csharp": "_extract_csharp_java",
        "c_sharp": "_extract_csharp_java",
        "cs": "_extract_csharp_java",
    }

    @staticmethod
    def extract_annotations(node: tree_sitter.Node, code_bytes: bytes, language: str) -> Dict[str, Any]:
        """
        Extracts metadata tags including:
        - decorators: list of decorator / attribute strings (e.g. ['@classmethod', '#[no_mangle]'])
        - visibility: 'public', 'private', 'protected', 'package-private', etc.
        - is_async: bool
        - is_static: bool
        - is_abstract: bool
        """
        result = {
            "decorators": [],
            "visibility": "public",
            "is_async": False,
            "is_static": False,
            "is_abstract": False,
        }

        handler_name = AnnotationExtractor._DISPATCH_TABLE.get(language.lower())
        if handler_name:
            handler = getattr(AnnotationExtractor, handler_name)
            handler(node, code_bytes, result)

        return result

    @staticmethod
    def _extract_python(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        # In python, decorators can wrap function_definition or class_definition inside decorated_definition
        parent = node.parent
        target_node = node
        if parent and parent.type == "decorated_definition":
            target_node = parent

        if target_node.type == "decorated_definition":
            for child in target_node.children:
                if child.type == "decorator":
                    dec_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                    result["decorators"].append(dec_text)
                    if "@staticmethod" in dec_text:
                        result["is_static"] = True
                    if "@abstractmethod" in dec_text:
                        result["is_abstract"] = True

        # Check async
        for child in node.children:
            if child.type == "async":
                result["is_async"] = True

        # Visibility from name convention (_ prefix = private)
        name_node = node.child_by_field_name("name")
        if name_node:
            name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            if name.startswith("__") and not name.endswith("__"):
                result["visibility"] = "private"
            elif name.startswith("_"):
                result["visibility"] = "protected"
            else:
                result["visibility"] = "public"

    @staticmethod
    def _extract_rust(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        # Rust outer attributes: #[...]
        result["visibility"] = "private"  # Default in Rust

        # Inspect preceding siblings for outer attributes (e.g. #[no_mangle])
        curr = node.prev_sibling
        preceding_attrs = []
        while curr:
            if curr.type == "attribute_item":
                attr_text = code_bytes[curr.start_byte:curr.end_byte].decode("utf-8", errors="replace").strip()
                preceding_attrs.insert(0, attr_text)
            elif curr.type in ("comment", "line_comment", "block_comment"):
                pass
            else:
                break
            curr = curr.prev_sibling

        for attr in preceding_attrs:
            if attr not in result["decorators"]:
                result["decorators"].append(attr)

        for child in node.children:
            if child.type == "attribute_item":
                attr_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                if attr_text not in result["decorators"]:
                    result["decorators"].append(attr_text)
            elif child.type == "visibility_modifier":
                vis_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                result["visibility"] = vis_text
            elif child.type == "async":
                result["is_async"] = True

    @staticmethod
    def _extract_typescript(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        # TypeScript decorators and modifiers
        for child in node.children:
            if child.type == "decorator":
                dec_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                result["decorators"].append(dec_text)
            elif child.type == "accessibility_modifier":
                vis_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                result["visibility"] = vis_text
            elif child.type == "async":
                result["is_async"] = True
            elif child.type == "static":
                result["is_static"] = True
            elif child.type == "abstract":
                result["is_abstract"] = True

        # Check export
        parent = node.parent
        if parent and parent.type in ("export_statement", "export_declaration"):
            result["visibility"] = "public"

    @staticmethod
    def _extract_go(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        name_node = node.child_by_field_name("name")
        if name_node:
            name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            if name and name[0].isupper():
                result["visibility"] = "public"
            else:
                result["visibility"] = "package-private"

    @staticmethod
    def _extract_csharp_java(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        for child in node.children:
            if child.type in ("modifiers", "attribute_list", "annotation"):
                text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                if child.type in ("attribute_list", "annotation"):
                    result["decorators"].append(text)
                else:
                    if "public" in text:
                        result["visibility"] = "public"
                    elif "private" in text:
                        result["visibility"] = "private"
                    elif "protected" in text:
                        result["visibility"] = "protected"
                    if "static" in text:
                        result["is_static"] = True
                    if "abstract" in text:
                        result["is_abstract"] = True
                    if "async" in text:
                        result["is_async"] = True
