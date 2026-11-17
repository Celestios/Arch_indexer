"""
Tree-sitter AST annotation and attribute extraction.
Extracts decorators, attributes, visibility modifiers, and compiler tags from declaration nodes.
"""
from typing import List, Dict, Any, Optional
import tree_sitter


class AnnotationExtractor:
    """Extracts decorators, attributes, and visibility modifiers from AST nodes."""

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

        lang = language.lower()
        if lang == "python":
            AnnotationExtractor._extract_python(node, code_bytes, result)
        elif lang == "rust":
            AnnotationExtractor._extract_rust(node, code_bytes, result)
        elif lang in ("typescript", "tsx", "javascript"):
            AnnotationExtractor._extract_typescript(node, code_bytes, result)
        elif lang == "go":
            AnnotationExtractor._extract_go(node, code_bytes, result)
        elif lang in ("java", "csharp", "c_sharp"):
            AnnotationExtractor._extract_csharp_java(node, code_bytes, result)

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
        for child in node.children:
            if child.type == "attribute_item":
                attr_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
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
