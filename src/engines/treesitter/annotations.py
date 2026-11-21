"""Tree-sitter AST annotation and attribute extraction."""
from typing import Dict, Any
import tree_sitter
from engines.registry import LanguageRegistry


def _extract_python(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
    parent = node.parent
    target_node = parent if (parent and parent.type == "decorated_definition") else node

    if target_node.type == "decorated_definition":
        for child in target_node.children:
            if child.type == "decorator":
                dec_text = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
                result["decorators"].append(dec_text)
                if "@staticmethod" in dec_text:
                    result["is_static"] = True
                if "@abstractmethod" in dec_text:
                    result["is_abstract"] = True

    for child in node.children:
        if child.type == "async":
            result["is_async"] = True

    name_node = node.child_by_field_name("name")
    if name_node:
        name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        if name.startswith("__") and not name.endswith("__"):
            result["visibility"] = "private"
        elif name.startswith("_"):
            result["visibility"] = "protected"
        else:
            result["visibility"] = "public"


def _extract_rust(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
    result["visibility"] = "private"
    curr = node.prev_sibling
    preceding_attrs = []
    while curr:
        if curr.type == "attribute_item":
            preceding_attrs.insert(0, code_bytes[curr.start_byte:curr.end_byte].decode("utf-8", errors="replace").strip())
        elif curr.type not in ("comment", "line_comment", "block_comment"):
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
            result["visibility"] = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
        elif child.type == "async":
            result["is_async"] = True


def _extract_typescript(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
    for child in node.children:
        if child.type == "decorator":
            result["decorators"].append(code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip())
        elif child.type == "accessibility_modifier":
            result["visibility"] = code_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
        elif child.type == "async":
            result["is_async"] = True
        elif child.type == "static":
            result["is_static"] = True
        elif child.type == "abstract":
            result["is_abstract"] = True

    if node.parent and node.parent.type in ("export_statement", "export_declaration"):
        result["visibility"] = "public"


def _extract_go(node: tree_sitter.Node, code_bytes: bytes, result: Dict[str, Any]):
    name_node = node.child_by_field_name("name")
    if name_node:
        name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        result["visibility"] = "public" if (name and name[0].isupper()) else "package-private"


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


_EXTRACTORS = {
    "python": _extract_python,
    "rust": _extract_rust,
    "typescript": _extract_typescript,
    "javascript": _extract_typescript,
    "go": _extract_go,
    "java": _extract_csharp_java,
    "csharp": _extract_csharp_java,
}


def extract_annotations(node: tree_sitter.Node, code_bytes: bytes, language: str) -> Dict[str, Any]:
    """Extracts decorators, visibility, async, static, and abstract metadata tags."""
    result: Dict[str, Any] = {
        "decorators": [],
        "visibility": "public",
        "is_async": False,
        "is_static": False,
        "is_abstract": False,
    }
    spec = LanguageRegistry.get_spec(language)
    lang_name = spec.name if spec else language.lower()
    handler = _EXTRACTORS.get(lang_name)
    if handler:
        handler(node, code_bytes, result)
    return result
