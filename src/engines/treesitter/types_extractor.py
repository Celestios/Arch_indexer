"""
Tree-sitter AST type annotation extractor.
Extracts syntactic parameter types and return type annotations from function/method declarations.
"""
from typing import List, Dict, Any, Optional
import tree_sitter


class TypesExtractor:
    """Extracts syntactic types from declaration nodes."""

    _DISPATCH_TABLE = {
        "python": "_extract_python",
        "rust": "_extract_rust",
        "typescript": "_extract_typescript",
        "tsx": "_extract_typescript",
        "javascript": "_extract_typescript",
        "js": "_extract_typescript",
    }

    @classmethod
    def extract_types(cls, node: tree_sitter.Node, code_bytes: bytes, language: str) -> Dict[str, Any]:
        """
        Extracts:
        - parameters: list of {'name': str, 'type': Optional[str], 'default': Optional[str]}
        - return_type: Optional[str]
        """
        result: Dict[str, Any] = {
            "parameters": [],
            "return_type": None,
        }

        handler_name = cls._DISPATCH_TABLE.get(language.lower())
        if handler_name:
            handler = getattr(cls, handler_name)
            handler(node, code_bytes, result)

        return result

    @classmethod
    def _extract_python(cls, node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for child in params_node.children:
                if child.type == "identifier":
                    name = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
                    result["parameters"].append({"name": name, "type": None, "default": None})
                elif child.type == "typed_parameter":
                    # identifier, type
                    name_child = child.child_by_field_name("name") or (child.children[0] if child.children else None)
                    type_child = child.child_by_field_name("type") or (child.children[2] if len(child.children) > 2 else None)
                    name = code_bytes[name_child.start_byte:name_child.end_byte].decode("utf-8", errors="replace") if name_child else ""
                    typ = code_bytes[type_child.start_byte:type_child.end_byte].decode("utf-8", errors="replace") if type_child else None
                    result["parameters"].append({"name": name, "type": typ, "default": None})
                elif child.type == "default_parameter":
                    name_child = child.child_by_field_name("name")
                    val_child = child.child_by_field_name("value")
                    name = code_bytes[name_child.start_byte:name_child.end_byte].decode("utf-8", errors="replace") if name_child else ""
                    val = code_bytes[val_child.start_byte:val_child.end_byte].decode("utf-8", errors="replace") if val_child else None
                    result["parameters"].append({"name": name, "type": None, "default": val})
                elif child.type == "typed_default_parameter":
                    name_child = child.child_by_field_name("name")
                    type_child = child.child_by_field_name("type")
                    val_child = child.child_by_field_name("value")
                    name = code_bytes[name_child.start_byte:name_child.end_byte].decode("utf-8", errors="replace") if name_child else ""
                    typ = code_bytes[type_child.start_byte:type_child.end_byte].decode("utf-8", errors="replace") if type_child else None
                    val = code_bytes[val_child.start_byte:val_child.end_byte].decode("utf-8", errors="replace") if val_child else None
                    result["parameters"].append({"name": name, "type": typ, "default": val})

        ret_node = node.child_by_field_name("return_type")
        if ret_node:
            ret_str = code_bytes[ret_node.start_byte:ret_node.end_byte].decode("utf-8", errors="replace").strip()
            result["return_type"] = ret_str

    @classmethod
    def _extract_rust(cls, node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for child in params_node.children:
                if child.type == "parameter":
                    pattern = child.child_by_field_name("pattern")
                    type_node = child.child_by_field_name("type")
                    name = code_bytes[pattern.start_byte:pattern.end_byte].decode("utf-8", errors="replace") if pattern else ""
                    typ = code_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace") if type_node else None
                    result["parameters"].append({"name": name, "type": typ, "default": None})
                elif child.type in ("self_parameter",):
                    result["parameters"].append({"name": "self", "type": None, "default": None})

        ret_node = node.child_by_field_name("return_type")
        if ret_node:
            ret_str = code_bytes[ret_node.start_byte:ret_node.end_byte].decode("utf-8", errors="replace").strip()
            # In Rust return_type starts with ->
            if ret_str.startswith("->"):
                ret_str = ret_str[2:].strip()
            result["return_type"] = ret_str

    @classmethod
    def _extract_typescript(cls, node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for child in params_node.children:
                if child.type in ("required_parameter", "optional_parameter"):
                    pattern = child.child_by_field_name("pattern")
                    type_node = child.child_by_field_name("type")
                    val_node = child.child_by_field_name("value")
                    name = code_bytes[pattern.start_byte:pattern.end_byte].decode("utf-8", errors="replace") if pattern else ""
                    typ = code_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace") if type_node else None
                    if typ and typ.startswith(":"):
                        typ = typ[1:].strip()
                    val = code_bytes[val_node.start_byte:val_node.end_byte].decode("utf-8", errors="replace") if val_node else None
                    result["parameters"].append({"name": name, "type": typ, "default": val})

        ret_node = node.child_by_field_name("return_type")
        if ret_node:
            ret_str = code_bytes[ret_node.start_byte:ret_node.end_byte].decode("utf-8", errors="replace").strip()
            if ret_str.startswith(":"):
                ret_str = ret_str[1:].strip()
            result["return_type"] = ret_str
