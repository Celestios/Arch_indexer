"""Tree-sitter structural anti-pattern rules."""
from typing import List, Dict, Any, Union
from pathlib import Path
import tree_sitter
from engines.registry import LanguageRegistry
from engines.treesitter.loader import get_parser


def _check_python(root: tree_sitter.Node, code_bytes: bytes, filepath: str, violations: List[Dict[str, Any]]):
    def visit(node: tree_sitter.Node):
        if node.type == "except_clause":
            has_type = any(child.type not in ("except", ":", "block", "comment") for child in node.children)
            if not has_type:
                violations.append({
                    "rule_id": "ANTI_BARE_EXCEPT",
                    "filepath": filepath,
                    "line": node.start_point.row + 1,
                    "col": node.start_point.column,
                    "severity": "Warning",
                    "message": "Bare 'except:' catches all exceptions including KeyboardInterrupt and SystemExit. Catch Exception instead.",
                })
        elif node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node and func_node.type == "identifier":
                func_name = code_bytes[func_node.start_byte:func_node.end_byte].decode("utf-8", errors="replace")
                if func_name in ("eval", "exec"):
                    violations.append({
                        "rule_id": "ANTI_DANGEROUS_EXEC",
                        "filepath": filepath,
                        "line": func_node.start_point.row + 1,
                        "col": func_node.start_point.column,
                        "severity": "Error",
                        "message": f"Dangerous dynamic execution via '{func_name}()'. Avoid in production code.",
                    })
        for child in node.children:
            visit(child)

    visit(root)


def _check_rust(root: tree_sitter.Node, code_bytes: bytes, filepath: str, violations: List[Dict[str, Any]]):
    if "test" in filepath.lower():
        return

    def visit(node: tree_sitter.Node):
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node and func_node.type == "field_expression":
                field = func_node.child_by_field_name("field")
                if field and code_bytes[field.start_byte:field.end_byte].decode("utf-8", errors="replace") == "unwrap":
                    violations.append({
                        "rule_id": "ANTI_RUST_UNWRAP",
                        "filepath": filepath,
                        "line": field.start_point.row + 1,
                        "col": field.start_point.column,
                        "severity": "Warning",
                        "message": "Direct '.unwrap()' in production code can panic. Use '?', 'expect()', or match.",
                    })
        for child in node.children:
            visit(child)

    visit(root)


def _check_typescript(root: tree_sitter.Node, code_bytes: bytes, filepath: str, violations: List[Dict[str, Any]]):
    def visit(node: tree_sitter.Node):
        if node.type == "predefined_type":
            if code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace") == "any":
                violations.append({
                    "rule_id": "ANTI_TS_ANY",
                    "filepath": filepath,
                    "line": node.start_point.row + 1,
                    "col": node.start_point.column,
                    "severity": "Info",
                    "message": "Use of explicit 'any' type disables type safety. Consider 'unknown' or a strict interface.",
                })
        for child in node.children:
            visit(child)

    visit(root)


_CHECKERS = {
    "python": _check_python,
    "rust": _check_rust,
    "typescript": _check_typescript,
    "javascript": _check_typescript,
}


def check_file(filepath: Union[str, Path], source: Union[str, bytes], language: str) -> List[Dict[str, Any]]:
    """Scans a file for structural anti-patterns and returns violations."""
    code_bytes = source.encode("utf-8") if isinstance(source, str) else source
    parser = get_parser(language)
    if not parser:
        return []
    tree = parser.parse(code_bytes)
    if not tree or not tree.root_node:
        return []

    violations: List[Dict[str, Any]] = []
    spec = LanguageRegistry.get_spec(language)
    lang_name = spec.name if spec else language.lower()
    handler = _CHECKERS.get(lang_name)
    if handler:
        handler(tree.root_node, code_bytes, str(filepath).replace("\\", "/"), violations)
    return violations
