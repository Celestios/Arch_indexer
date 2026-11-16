"""
Code Extractor Module.
Extracts defining code blocks for methods, functions, constructors, and classes
from source files on disk via AST analysis with indentation/brace fallback.
"""

import ast
import os
from typing import Dict, List, Optional, Tuple, Any


class CodeExtractor:
    """
    Extracts source code definitions for symbols by file path, line numbers,
    and symbol identifiers using AST walking and syntactic heuristics.
    """

    def __init__(self, root_dir: str = "."):
        self.root_dir = os.path.abspath(root_dir)
        self._files_cache: Dict[str, List[str]] = {}
        self._ast_cache: Dict[str, Dict[str, Any]] = {}

    def _resolve_path(self, filepath: str) -> str:
        clean = filepath.replace("\\", "/").lstrip("/")
        if os.path.isabs(filepath) and os.path.exists(filepath):
            return filepath
        candidate = os.path.join(self.root_dir, clean)
        if os.path.exists(candidate):
            return candidate
        if os.path.exists(clean):
            return os.path.abspath(clean)
        return candidate

    def get_file_lines(self, filepath: str) -> List[str]:
        full_path = self._resolve_path(filepath)
        if full_path not in self._files_cache:
            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        self._files_cache[full_path] = f.readlines()
                except Exception:
                    self._files_cache[full_path] = []
            else:
                self._files_cache[full_path] = []
        return self._files_cache[full_path]

    def _parse_python_ast(self, full_path: str, lines: List[str]) -> Dict[str, Any]:
        if full_path in self._ast_cache:
            return self._ast_cache[full_path]

        data = {"by_line": {}, "by_name": {}, "by_qname": {}}
        try:
            tree = ast.parse("".join(lines), filename=full_path)

            def walk_stmts(parent_qname: str, stmts: List[ast.AST]):
                for node in stmts:
                    if isinstance(node, ast.ClassDef):
                        s = min([d.lineno for d in node.decorator_list] + [node.lineno])
                        e = node.end_lineno or node.lineno
                        code = "".join(lines[s - 1 : e])
                        info = (s, e, code)
                        data["by_line"][s] = info
                        data["by_line"][node.lineno] = info
                        data["by_name"][node.name] = info
                        qname = f"{parent_qname}.{node.name}" if parent_qname else node.name
                        data["by_qname"][qname] = info
                        walk_stmts(node.name, node.body)

                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        s = min([d.lineno for d in node.decorator_list] + [node.lineno])
                        e = node.end_lineno or node.lineno
                        code = "".join(lines[s - 1 : e])
                        info = (s, e, code)
                        data["by_line"][s] = info
                        data["by_line"][node.lineno] = info
                        if node.name not in data["by_name"]:
                            data["by_name"][node.name] = info
                        qname = f"{parent_qname}.{node.name}" if parent_qname else node.name
                        data["by_qname"][qname] = info
                        walk_stmts(qname, node.body)

            walk_stmts("", tree.body)
        except Exception:
            pass

        self._ast_cache[full_path] = data
        return data

    def extract_code(
        self,
        filepath: str,
        label: str,
        raw_symbol: Optional[str] = None,
        line: Optional[int] = None,
        parent_class: Optional[str] = None,
    ) -> Optional[Tuple[int, int, str]]:
        """
        Extracts the defining code block for a symbol.
        Returns (start_line, end_line, code_string) or None if unavailable.
        """
        if not filepath:
            return None

        lines = self.get_file_lines(filepath)
        if not lines:
            return None

        clean_path = filepath.replace("\\", "/")
        full_path = self._resolve_path(filepath)

        # 1. AST Analysis for Python files
        if clean_path.endswith(".py"):
            py_data = self._parse_python_ast(full_path, lines)

            # A. Match by exact start line
            if line and line in py_data["by_line"]:
                return py_data["by_line"][line]
            if line and (line + 1) in py_data["by_line"]:
                return py_data["by_line"][line + 1]

            # B. Match by qualified name (ParentClass.method_name)
            clean_label = label.rstrip("()").split("#")[-1]
            if parent_class:
                clean_cls = parent_class.split(":")[-1].split("#")[0].split("/")[-1]
                qname = f"{clean_cls}.{clean_label}"
                if qname in py_data["by_qname"]:
                    return py_data["by_qname"][qname]

            # C. Match by clean symbol name
            if clean_label in py_data["by_name"]:
                return py_data["by_name"][clean_label]

            # D. Match by raw SCIP descriptor
            if raw_symbol:
                desc = raw_symbol.split()[-1].replace("`", "").rstrip(".").rstrip("()").rstrip("#")
                sym_name = desc.split("/")[-1].split("#")[-1]
                if sym_name in py_data["by_name"]:
                    return py_data["by_name"][sym_name]

        # 2. Indentation / Braces heuristic fallback for all languages or non-AST files
        if line and 1 <= line <= len(lines):
            start_idx = line - 1
            decl_line = lines[start_idx]
            indent = len(decl_line) - len(decl_line.lstrip())
            has_braces = "{" in decl_line
            brace_count = decl_line.count("{") - decl_line.count("}")
            max_lines = min(len(lines), start_idx + 400)
            end_idx = start_idx + 1

            if has_braces:
                while end_idx < max_lines:
                    cur = lines[end_idx]
                    brace_count += cur.count("{") - cur.count("}")
                    end_idx += 1
                    if brace_count <= 0:
                        break
            else:
                while end_idx < max_lines:
                    cur = lines[end_idx]
                    cur_stripped = cur.strip()
                    if cur_stripped:
                        cur_indent = len(cur) - len(cur.lstrip())
                        if cur_indent <= indent and not cur_stripped.startswith("#"):
                            break
                    end_idx += 1

            code = "".join(lines[start_idx:end_idx])
            return (line, end_idx, code)

        return None
