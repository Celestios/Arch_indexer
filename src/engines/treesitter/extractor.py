"""
Tree-sitter AST symbol extractor.
Performs high-performance (<2ms), robust syntactic symbol declaration extraction across languages.
Extracts:
- Exact multi-line signatures
- Clean docstrings
- 1-indexed line and 0-indexed column coordinates
- Enclosing AST scope / parent_symbol
- Body SHA-256 hash for incremental churn tracking
- Defining code blocks
- Decorators and visibility annotations
- Structural metrics (complexity, nesting depth, LOC)
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import tree_sitter

from engines.treesitter.loader import TreesitterLoader
from engines.treesitter.annotations import AnnotationExtractor
from engines.treesitter.metrics import MetricsCalculator
from engines.treesitter.types_extractor import TypesExtractor


class SymbolDeclaration:
    """Represents a symbol declaration extracted via Tree-sitter AST."""

    def __init__(
        self,
        name: str,
        clean_symbol: str,
        kind: str,
        filepath: str,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
        signature: str,
        docstring: str = "",
        body_hash: str = "",
        parent_symbol: Optional[str] = None,
        code_block: Optional[str] = None,
        annotations: Optional[Dict[str, Any]] = None,
        complexity: int = 1,
        nesting_depth: int = 0,
        loc: int = 1,
    ):
        self.name = name
        if clean_symbol:
            # Strip drive letters (e.g. C:, D:, C:/, D:\, D:.)
            cs = re.sub(r"^[a-zA-Z]:[./\\]*", "", clean_symbol)
            cs = cs.replace("\\", "/")
            for root_marker in ("/src/", "/lib/", "/app/", "/test/", "/tests/", ".src.", ".lib.", ".app.", ".test.", ".tests."):
                if root_marker in cs:
                    cs = cs[cs.rfind(root_marker) + len(root_marker):]
                    break
            for prefix in ("src/", "lib/", "app/", "test/", "tests/", "src.", "lib.", "app.", "test.", "tests."):
                if cs.startswith(prefix):
                    cs = cs[len(prefix):]
                    break
            cs = cs.lstrip("./\\").replace("/", ".")
            cs = re.sub(r"\.+", ".", cs).strip(".")
            clean_symbol = cs

        self.clean_symbol = clean_symbol
        self.symbol = clean_symbol  # Default symbol ID to clean_symbol; can be reconciled with SCIP
        self.kind = kind
        self.filepath = str(filepath).replace("\\", "/")
        self.start_line = start_line
        self.start_col = start_col
        self.end_line = end_line
        self.end_col = end_col
        self.signature = signature
        self.docstring = docstring
        self.body_hash = body_hash
        self.parent_symbol = parent_symbol
        self.code_block = code_block
        self.annotations = annotations or {}
        self.complexity = complexity
        self.nesting_depth = nesting_depth
        self.loc = loc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "clean_symbol": self.clean_symbol,
            "kind": self.kind,
            "filepath": self.filepath,
            "start_line": self.start_line,
            "start_col": self.start_col,
            "end_line": self.end_line,
            "end_col": self.end_col,
            "signature": self.signature,
            "docstring": self.docstring,
            "body_hash": self.body_hash,
            "parent_symbol": self.parent_symbol,
            "code_block": self.code_block,
            "annotations": self.annotations,
            "complexity": self.complexity,
            "nesting_depth": self.nesting_depth,
            "loc": self.loc,
        }


class TreesitterExtractor:
    """High-speed AST symbol declaration extractor."""

    @classmethod
    def extract_symbols_from_file(
        cls,
        filepath: str | Path,
        source: Optional[str | bytes] = None,
        project_root: Optional[Path] = None,
    ) -> List[SymbolDeclaration]:
        """Extracts symbol declarations from a file."""
        fp = Path(filepath)
        if project_root:
            try:
                norm_fp = str(Path(filepath).resolve().relative_to(Path(project_root).resolve())).replace("\\", "/")
            except Exception:
                norm_fp = str(filepath).replace("\\", "/")
        else:
            norm_fp = str(filepath).replace("\\", "/")

        norm_fp = norm_fp.replace("\\", "/")
        if norm_fp.startswith("./"):
            norm_fp = norm_fp[2:]

        if source is None:
            if not fp.exists():
                return []
            code_bytes = fp.read_bytes()
        elif isinstance(source, str):
            code_bytes = source.encode("utf-8")
        else:
            code_bytes = source

        language = TreesitterLoader.detect_language(fp)
        if not language:
            return []

        parser = TreesitterLoader.get_parser(language)
        if not parser:
            return []

        tree = parser.parse(code_bytes)
        if not tree or not tree.root_node:
            return []

        # Derive module prefix from filepath
        module_prefix = cls._derive_module_prefix(norm_fp)

        if language in ("tsx", "javascript", "jsx"):
            extractor_fn = cls._extract_typescript
        else:
            extractor_fn = getattr(cls, f"_extract_{language}", None)

        if not extractor_fn:
            # Fallback for generic C-like / other languages
            extractor_fn = cls._extract_generic

        return extractor_fn(tree.root_node, code_bytes, norm_fp, module_prefix, language)

    @classmethod
    def _derive_module_prefix(cls, filepath: str) -> str:
        """Derives a dot-separated module prefix from filepath (e.g. src/db/connection.py -> db.connection)."""
        p = filepath.replace("\\", "/")
        # Strip Windows drive letter (e.g. C:/, D:/, C:)
        p = re.sub(r"^[a-zA-Z]:/*", "", p)
        # Strip leading slashes
        p = p.lstrip("/")

        # If it's an absolute path that still contains common root folders, take from that root folder
        for root_marker in ("/src/", "/lib/", "/app/", "/test/", "/tests/"):
            if root_marker in p:
                p = p[p.rfind(root_marker) + 1:]
                break

        # Remove common root folders
        for prefix in ("src/", "lib/", "app/", "test/", "tests/"):
            if p.startswith(prefix):
                p = p[len(prefix):]
                break

        # Remove file extension
        stem = p.rsplit(".", 1)[0] if "." in p else p
        stem = stem.replace("/", ".")
        if stem.endswith(".__init__"):
            stem = stem[:-9]
        stem = re.sub(r"\.+", ".", stem).strip(".")
        return stem

    @classmethod
    def _extract_python(
        cls,
        root: tree_sitter.Node,
        code_bytes: bytes,
        filepath: str,
        module_prefix: str,
        language: str,
    ) -> List[SymbolDeclaration]:
        symbols: List[SymbolDeclaration] = []

        def visit(node: tree_sitter.Node, parent_scope: str, parent_clean: Optional[str]):
            actual_node = node
            # If wrapped in decorated_definition, inspect inner definition
            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type in ("class_definition", "function_definition"):
                        actual_node = child
                        break

            if actual_node.type == "class_definition":
                name_node = actual_node.child_by_field_name("name")
                body_node = actual_node.child_by_field_name("body")
                if name_node and body_node:
                    class_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    clean_sym = f"{parent_scope}.{class_name}" if parent_scope else class_name
                    
                    # Signature: from node start (or actual_node start) to body start
                    sig_bytes = code_bytes[actual_node.start_byte:body_node.start_byte].strip()
                    sig = sig_bytes.decode("utf-8", errors="replace")
                    
                    # Docstring: first string expression statement in body
                    doc = cls._extract_python_docstring(body_node, code_bytes)
                    
                    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte]
                    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
                    code_block = code_bytes[actual_node.start_byte:actual_node.end_byte].decode("utf-8", errors="replace")
                    annotations = AnnotationExtractor.extract_annotations(actual_node, code_bytes, language)
                    metrics = MetricsCalculator.calculate_metrics(actual_node, code_bytes)

                    sym_decl = SymbolDeclaration(
                        name=class_name,
                        clean_symbol=clean_sym,
                        kind="Class",
                        filepath=filepath,
                        start_line=actual_node.start_point.row + 1,
                        start_col=actual_node.start_point.column,
                        end_line=actual_node.end_point.row + 1,
                        end_col=actual_node.end_point.column,
                        signature=sig,
                        docstring=doc,
                        body_hash=b_hash,
                        parent_symbol=parent_clean,
                        code_block=code_block,
                        annotations=annotations,
                        complexity=metrics["cyclomatic_complexity"],
                        nesting_depth=metrics["max_nesting_depth"],
                        loc=metrics["loc"],
                    )
                    symbols.append(sym_decl)

                    # Recurse inside class body
                    for child in body_node.children:
                        visit(child, clean_sym, clean_sym)
                    return

            elif actual_node.type == "function_definition":
                name_node = actual_node.child_by_field_name("name")
                body_node = actual_node.child_by_field_name("body")
                if name_node and body_node:
                    fn_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    kind = "Method" if parent_clean else "Function"
                    if fn_name == "__init__":
                        kind = "Constructor"
                    clean_sym = f"{parent_scope}.{fn_name}()" if parent_scope else f"{fn_name}()"

                    sig_bytes = code_bytes[actual_node.start_byte:body_node.start_byte].strip()
                    sig = sig_bytes.decode("utf-8", errors="replace")
                    doc = cls._extract_python_docstring(body_node, code_bytes)

                    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte]
                    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
                    code_block = code_bytes[actual_node.start_byte:actual_node.end_byte].decode("utf-8", errors="replace")
                    annotations = AnnotationExtractor.extract_annotations(actual_node, code_bytes, language)
                    metrics = MetricsCalculator.calculate_metrics(actual_node, code_bytes)

                    sym_decl = SymbolDeclaration(
                        name=fn_name,
                        clean_symbol=clean_sym,
                        kind=kind,
                        filepath=filepath,
                        start_line=actual_node.start_point.row + 1,
                        start_col=actual_node.start_point.column,
                        end_line=actual_node.end_point.row + 1,
                        end_col=actual_node.end_point.column,
                        signature=sig,
                        docstring=doc,
                        body_hash=b_hash,
                        parent_symbol=parent_clean,
                        code_block=code_block,
                        annotations=annotations,
                        complexity=metrics["cyclomatic_complexity"],
                        nesting_depth=metrics["max_nesting_depth"],
                        loc=metrics["loc"],
                    )
                    symbols.append(sym_decl)

                    # Also visit nested functions if any
                    for child in body_node.children:
                        visit(child, clean_sym[:-2], clean_sym)
                    return

            for child in node.children:
                visit(child, parent_scope, parent_clean)

        visit(root, module_prefix, None)
        return symbols

    @classmethod
    def _extract_python_docstring(cls, body_node: tree_sitter.Node, code_bytes: bytes) -> str:
        if not body_node or not body_node.children:
            return ""
        first = body_node.children[0]
        if first.type == "expression_statement" and first.children:
            target = first.children[0]
            if target.type == "string":
                raw_text = code_bytes[target.start_byte:target.end_byte].decode("utf-8", errors="replace")
                # Strip quotes (""" or ''' or " or ')
                for q in ('"""', "'''", '"', "'"):
                    if raw_text.startswith(q) and raw_text.endswith(q) and len(raw_text) >= 2 * len(q):
                        raw_text = raw_text[len(q):-len(q)]
                        break
                return raw_text.strip()
        return ""

    @classmethod
    def _extract_rust(
        cls,
        root: tree_sitter.Node,
        code_bytes: bytes,
        filepath: str,
        module_prefix: str,
        language: str,
    ) -> List[SymbolDeclaration]:
        symbols: List[SymbolDeclaration] = []

        def visit(node: tree_sitter.Node, parent_scope: str, parent_clean: Optional[str]):
            kind = None
            if node.type == "struct_item":
                kind = "Struct"
            elif node.type == "enum_item":
                kind = "Enum"
            elif node.type == "trait_item":
                kind = "Trait"
            elif node.type == "function_item":
                kind = "Method" if parent_clean else "Function"
            elif node.type == "type_item":
                kind = "TypeAlias"

            if kind:
                name_node = node.child_by_field_name("name")
                if not name_node and node.child_by_field_name("declarator"):
                    decl = node.child_by_field_name("declarator")
                    while decl and decl.type in ("function_declarator", "pointer_declarator"):
                        sub_decl = decl.child_by_field_name("declarator")
                        if sub_decl:
                            decl = sub_decl
                        else:
                            break
                    if decl and decl.type == "identifier":
                        name_node = decl
                    elif decl:
                        name_node = decl.child_by_field_name("declarator") or decl

                body_node = node.child_by_field_name("body")
                if name_node:
                    item_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    is_callable = kind in ("Function", "Method")
                    clean_sym = f"{parent_scope}.{item_name}()" if is_callable else f"{parent_scope}.{item_name}"
                    if not parent_scope:
                        clean_sym = f"{item_name}()" if is_callable else item_name

                    # Signature
                    if body_node:
                        sig_bytes = code_bytes[node.start_byte:body_node.start_byte].strip()
                    else:
                        sig_bytes = code_bytes[node.start_byte:node.end_byte].strip()
                    sig = sig_bytes.decode("utf-8", errors="replace").rstrip("{").strip()

                    # Doc comment preceding node
                    doc = cls._extract_doc_comments(node, code_bytes)

                    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte] if body_node else b""
                    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
                    code_block = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                    annotations = AnnotationExtractor.extract_annotations(node, code_bytes, language)
                    metrics = MetricsCalculator.calculate_metrics(node, code_bytes)

                    sym_decl = SymbolDeclaration(
                        name=item_name,
                        clean_symbol=clean_sym,
                        kind=kind,
                        filepath=filepath,
                        start_line=node.start_point.row + 1,
                        start_col=node.start_point.column,
                        end_line=node.end_point.row + 1,
                        end_col=node.end_point.column,
                        signature=sig,
                        docstring=doc,
                        body_hash=b_hash,
                        parent_symbol=parent_clean,
                        code_block=code_block,
                        annotations=annotations,
                        complexity=metrics["cyclomatic_complexity"],
                        nesting_depth=metrics["max_nesting_depth"],
                        loc=metrics["loc"],
                    )
                    symbols.append(sym_decl)

                    if body_node and kind in ("Trait", "Struct"):
                        for child in body_node.children:
                            visit(child, clean_sym, clean_sym)
                    return

            elif node.type == "impl_item":
                # Find type being implemented
                type_node = node.child_by_field_name("type")
                body_node = node.child_by_field_name("body")
                impl_name = code_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace") if type_node else ""
                clean_impl = f"{module_prefix}.{impl_name}" if impl_name else module_prefix
                if body_node:
                    for child in body_node.children:
                        visit(child, clean_impl, clean_impl)
                return

            for child in node.children:
                visit(child, parent_scope, parent_clean)

        visit(root, module_prefix, None)
        return symbols

    @classmethod
    def _extract_typescript(
        cls,
        root: tree_sitter.Node,
        code_bytes: bytes,
        filepath: str,
        module_prefix: str,
        language: str,
    ) -> List[SymbolDeclaration]:
        symbols: List[SymbolDeclaration] = []

        def visit(node: tree_sitter.Node, parent_scope: str, parent_clean: Optional[str]):
            actual_node = node
            if node.type in ("export_statement", "export_declaration"):
                for child in node.children:
                    if child.type in (
                        "class_declaration", "interface_declaration", "type_alias_declaration",
                        "enum_declaration", "function_declaration"
                    ):
                        actual_node = child
                        break

            kind = None
            if actual_node.type == "class_declaration":
                kind = "Class"
            elif actual_node.type == "interface_declaration":
                kind = "Interface"
            elif actual_node.type == "type_alias_declaration":
                kind = "TypeAlias"
            elif actual_node.type == "enum_declaration":
                kind = "Enum"
            elif actual_node.type in ("function_declaration", "method_definition"):
                kind = "Method" if parent_clean else "Function"

            if kind:
                name_node = actual_node.child_by_field_name("name")
                body_node = actual_node.child_by_field_name("body")
                if name_node:
                    item_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    is_callable = kind in ("Function", "Method")
                    clean_sym = f"{parent_scope}.{item_name}()" if is_callable else f"{parent_scope}.{item_name}"

                    if body_node:
                        sig_bytes = code_bytes[actual_node.start_byte:body_node.start_byte].strip()
                    else:
                        sig_bytes = code_bytes[actual_node.start_byte:actual_node.end_byte].strip()
                    sig = sig_bytes.decode("utf-8", errors="replace").rstrip("{").strip()

                    doc = cls._extract_doc_comments(actual_node, code_bytes)
                    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte] if body_node else b""
                    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
                    code_block = code_bytes[actual_node.start_byte:actual_node.end_byte].decode("utf-8", errors="replace")
                    annotations = AnnotationExtractor.extract_annotations(actual_node, code_bytes, language)
                    metrics = MetricsCalculator.calculate_metrics(actual_node, code_bytes)

                    sym_decl = SymbolDeclaration(
                        name=item_name,
                        clean_symbol=clean_sym,
                        kind=kind,
                        filepath=filepath,
                        start_line=actual_node.start_point.row + 1,
                        start_col=actual_node.start_point.column,
                        end_line=actual_node.end_point.row + 1,
                        end_col=actual_node.end_point.column,
                        signature=sig,
                        docstring=doc,
                        body_hash=b_hash,
                        parent_symbol=parent_clean,
                        code_block=code_block,
                        annotations=annotations,
                        complexity=metrics["cyclomatic_complexity"],
                        nesting_depth=metrics["max_nesting_depth"],
                        loc=metrics["loc"],
                    )
                    symbols.append(sym_decl)

                    if body_node and kind in ("Class", "Interface"):
                        for child in body_node.children:
                            visit(child, clean_sym, clean_sym)
                    return

            for child in node.children:
                visit(child, parent_scope, parent_clean)

        visit(root, module_prefix, None)
        return symbols

    @classmethod
    def _extract_generic(
        cls,
        root: tree_sitter.Node,
        code_bytes: bytes,
        filepath: str,
        module_prefix: str,
        language: str,
    ) -> List[SymbolDeclaration]:
        """Generic fallback extractor for Go, C/C++, C#, Java, etc."""
        symbols: List[SymbolDeclaration] = []

        def visit(node: tree_sitter.Node, parent_scope: str, parent_clean: Optional[str]):
            kind = None
            if "class" in node.type:
                kind = "Class"
            elif "interface" in node.type:
                kind = "Interface"
            elif "struct" in node.type:
                kind = "Struct"
            elif "enum" in node.type:
                kind = "Enum"
            elif "function" in node.type or "method" in node.type:
                kind = "Method" if parent_clean else "Function"

            if kind:
                name_node = node.child_by_field_name("name")
                if not name_node and node.child_by_field_name("declarator"):
                    decl = node.child_by_field_name("declarator")
                    while decl and decl.type in ("function_declarator", "pointer_declarator"):
                        sub_decl = decl.child_by_field_name("declarator")
                        if sub_decl:
                            decl = sub_decl
                        else:
                            break
                    if decl and decl.type == "identifier":
                        name_node = decl
                    elif decl:
                        name_node = decl.child_by_field_name("declarator") or decl

                body_node = node.child_by_field_name("body")
                if name_node:
                    item_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    is_callable = kind in ("Function", "Method")
                    clean_sym = f"{parent_scope}.{item_name}()" if is_callable else f"{parent_scope}.{item_name}"

                    if body_node:
                        sig_bytes = code_bytes[node.start_byte:body_node.start_byte].strip()
                    else:
                        sig_bytes = code_bytes[node.start_byte:node.end_byte].strip()
                    sig = sig_bytes.decode("utf-8", errors="replace").rstrip("{").strip()

                    doc = cls._extract_doc_comments(node, code_bytes)
                    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte] if body_node else b""
                    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
                    code_block = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                    annotations = AnnotationExtractor.extract_annotations(node, code_bytes, language)
                    metrics = MetricsCalculator.calculate_metrics(node, code_bytes)

                    sym_decl = SymbolDeclaration(
                        name=item_name,
                        clean_symbol=clean_sym,
                        kind=kind,
                        filepath=filepath,
                        start_line=node.start_point.row + 1,
                        start_col=node.start_point.column,
                        end_line=node.end_point.row + 1,
                        end_col=node.end_point.column,
                        signature=sig,
                        docstring=doc,
                        body_hash=b_hash,
                        parent_symbol=parent_clean,
                        code_block=code_block,
                        annotations=annotations,
                        complexity=metrics["cyclomatic_complexity"],
                        nesting_depth=metrics["max_nesting_depth"],
                        loc=metrics["loc"],
                    )
                    symbols.append(sym_decl)

                    if body_node and kind in ("Class", "Interface", "Struct"):
                        for child in body_node.children:
                            visit(child, clean_sym, clean_sym)
                    return

            for child in node.children:
                visit(child, parent_scope, parent_clean)

        visit(root, module_prefix, None)
        return symbols

    @classmethod
    def _extract_doc_comments(cls, node: tree_sitter.Node, code_bytes: bytes) -> str:
        """Extracts preceding doc comments (///, /**, //, #) from siblings right before the node."""
        target = node
        while target.parent and target.parent.type in ("export_statement", "export_declaration", "decorated_definition"):
            target = target.parent

        comments = []
        curr = target.prev_sibling
        while curr:
            if curr.type in ("comment", "line_comment", "block_comment"):
                text = code_bytes[curr.start_byte:curr.end_byte].decode("utf-8", errors="replace").strip()
                # Clean comment markers
                if text.startswith("///"):
                    text = text[3:].strip()
                elif text.startswith("/**"):
                    text = text[3:].rstrip("*/").strip()
                elif text.startswith("//"):
                    text = text[2:].strip()
                elif text.startswith("#") and not text.startswith("#["):
                    text = text[1:].strip()
                comments.insert(0, text)
            elif curr.type in ("attribute_item", "decorator"):
                pass  # Walk backward past intervening attributes / decorators
            else:
                break
            curr = curr.prev_sibling

        return "\n".join(comments)
