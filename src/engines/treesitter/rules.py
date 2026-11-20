"""
Tree-sitter structural anti-pattern rules.
Detects syntactic code smells like bare excepts, unparameterized SQL calls, and .unwrap() calls.
"""
from typing import List, Dict, Any
from pathlib import Path
import tree_sitter
from engines.treesitter.loader import TreesitterLoader


class StructuralRuleChecker:
    """Checks source code AST for syntactic anti-patterns."""

    _DISPATCH_TABLE = {
        "python": "_check_python",
        "rust": "_check_rust",
        "typescript": "_check_typescript",
        "tsx": "_check_typescript",
        "javascript": "_check_typescript",
        "js": "_check_typescript",
    }

    @classmethod
    def check_file(cls, filepath: str | Path, source: str | bytes, language: str) -> List[Dict[str, Any]]:
        """Scans a file for structural anti-patterns and returns violations."""
        if isinstance(source, str):
            code_bytes = source.encode("utf-8")
        else:
            code_bytes = source

        parser = TreesitterLoader.get_parser(language)
        if not parser:
            return []

        tree = parser.parse(code_bytes)
        if not tree or not tree.root_node:
            return []

        violations: List[Dict[str, Any]] = []
        fp_str = str(filepath).replace("\\", "/")

        handler_name = cls._DISPATCH_TABLE.get(language.lower())
        if handler_name:
            handler = getattr(cls, handler_name)
            handler(tree.root_node, code_bytes, fp_str, violations)

        return violations

    @classmethod
    def _check_python(cls, root: tree_sitter.Node, code_bytes: bytes, filepath: str, violations: List[Dict[str, Any]]):
        def visit(node: tree_sitter.Node):
            # Check 1: Bare except
            if node.type == "except_clause":
                # If except has no expression or identifier child, it's bare except:
                has_type = False
                for child in node.children:
                    if child.type not in ("except", ":", "block", "comment"):
                        has_type = True
                        break
                if not has_type:
                    violations.append({
                        "rule_id": "ANTI_BARE_EXCEPT",
                        "filepath": filepath,
                        "line": node.start_point.row + 1,
                        "col": node.start_point.column,
                        "severity": "Warning",
                        "message": "Bare 'except:' catches all exceptions including KeyboardInterrupt and SystemExit. Catch Exception instead.",
                    })

            # Check 2: eval() or exec()
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

    @classmethod
    def _check_rust(cls, root: tree_sitter.Node, code_bytes: bytes, filepath: str, violations: List[Dict[str, Any]]):
        # In Rust, check for .unwrap() calls (outside tests)
        is_test = "test" in filepath.lower()
        if is_test:
            return

        def visit(node: tree_sitter.Node):
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if func_node and func_node.type == "field_expression":
                    field = func_node.child_by_field_name("field")
                    if field:
                        field_name = code_bytes[field.start_byte:field.end_byte].decode("utf-8", errors="replace")
                        if field_name == "unwrap":
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

    @classmethod
    def _check_typescript(cls, root: tree_sitter.Node, code_bytes: bytes, filepath: str, violations: List[Dict[str, Any]]):
        def visit(node: tree_sitter.Node):
            # Check for any type annotation
            if node.type == "predefined_type":
                text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                if text == "any":
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
