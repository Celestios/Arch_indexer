"""Tree-sitter AST symbol declaration extractor."""
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
import tree_sitter

from engines.registry import LanguageRegistry
from engines.treesitter.loader import detect_language, get_parser
from engines.treesitter.annotations import extract_annotations
from engines.treesitter.metrics import calculate_metrics


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
        annotations: Optional[Dict[str, Any]] = None,
        complexity: int = 1,
        nesting_depth: int = 0,
        loc: int = 1,
    ):
        self.name = name
        if clean_symbol:
            cs = re.sub(r"^[a-zA-Z]:[./\\]*", "", clean_symbol).replace("\\", "/")
            for root_marker in ("/src/", "/lib/", "/app/", "/test/", "/tests/", ".src.", ".lib.", ".app.", ".test.", ".tests."):
                if root_marker in cs:
                    cs = cs[cs.rfind(root_marker) + len(root_marker):]
                    break
            for prefix in ("src/", "lib/", "app/", "test/", "tests/", "src.", "lib.", "app.", "test.", "tests."):
                if cs.startswith(prefix):
                    cs = cs[len(prefix):]
                    break
            cs = re.sub(r"\.+", ".", cs.lstrip("./\\").replace("/", ".")).strip(".")
            clean_symbol = cs

        self.clean_symbol = clean_symbol
        self.symbol = clean_symbol
        self.kind = kind
        norm_fp = str(filepath).replace("\\", "/")
        if norm_fp.startswith("./"):
            norm_fp = norm_fp[2:]
        self.filepath = norm_fp
        self.start_line = start_line
        self.start_col = start_col
        self.end_line = end_line
        self.end_col = end_col
        self.signature = signature
        self.docstring = docstring
        self.body_hash = body_hash
        self.parent_symbol = parent_symbol
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
            "annotations": self.annotations,
            "complexity": self.complexity,
            "nesting_depth": self.nesting_depth,
            "loc": self.loc,
        }


def _derive_module_prefix(filepath: str) -> str:
    p = re.sub(r"^[a-zA-Z]:/*", "", filepath.replace("\\", "/")).lstrip("/")
    for root_marker in ("/src/", "/lib/", "/app/", "/test/", "/tests/"):
        if root_marker in p:
            p = p[p.rfind(root_marker) + 1:]
            break
    for prefix in ("src/", "lib/", "app/", "test/", "tests/"):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    stem = (p.rsplit(".", 1)[0] if "." in p else p).replace("/", ".")
    if stem.endswith(".__init__"):
        stem = stem[:-9]
    return re.sub(r"\.+", ".", stem).strip(".")


def _extract_python_docstring(body_node: Optional[tree_sitter.Node], code_bytes: bytes) -> str:
    if not body_node or not body_node.children:
        return ""
    first = body_node.children[0]
    if first.type == "expression_statement" and first.children and first.children[0].type == "string":
        raw_text = code_bytes[first.children[0].start_byte:first.children[0].end_byte].decode("utf-8", errors="replace")
        for q in ('"""', "'''", '"', "'"):
            if raw_text.startswith(q) and raw_text.endswith(q) and len(raw_text) >= 2 * len(q):
                raw_text = raw_text[len(q):-len(q)]
                break
        return raw_text.strip()
    return ""


def _extract_doc_comments(node: tree_sitter.Node, code_bytes: bytes) -> str:
    target = node
    while target.parent and target.parent.type in ("export_statement", "export_declaration", "decorated_definition"):
        target = target.parent

    comments = []
    curr = target.prev_sibling
    while curr:
        if curr.type in ("comment", "line_comment", "block_comment"):
            text = code_bytes[curr.start_byte:curr.end_byte].decode("utf-8", errors="replace").strip()
            if text.startswith("///"):
                text = text[3:].strip()
            elif text.startswith("/**"):
                text = text[3:].rstrip("*/").strip()
            elif text.startswith("//"):
                text = text[2:].strip()
            elif text.startswith("#") and not text.startswith("#["):
                text = text[1:].strip()
            comments.insert(0, text)
        elif curr.type not in ("attribute_item", "decorator"):
            break
        curr = curr.prev_sibling

    return "\n".join(comments)


def _build_declaration(
    node: tree_sitter.Node,
    name: str,
    clean_symbol: str,
    kind: str,
    filepath: str,
    signature: str,
    docstring: str,
    body_node: Optional[tree_sitter.Node],
    code_bytes: bytes,
    parent_symbol: Optional[str],
    language: str,
) -> SymbolDeclaration:
    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte] if body_node else b""
    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
    annotations = extract_annotations(node, code_bytes, language)
    metrics = calculate_metrics(node, code_bytes)

    return SymbolDeclaration(
        name=name,
        clean_symbol=clean_symbol,
        kind=kind,
        filepath=filepath,
        start_line=node.start_point.row + 1,
        start_col=node.start_point.column,
        end_line=node.end_point.row + 1,
        end_col=node.end_point.column,
        signature=signature,
        docstring=docstring,
        body_hash=b_hash,
        parent_symbol=parent_symbol,
        annotations=annotations,
        complexity=metrics["cyclomatic_complexity"],
        nesting_depth=metrics["max_nesting_depth"],
        loc=metrics["loc"],
    )


def _extract_ast(
    root: tree_sitter.Node,
    code_bytes: bytes,
    filepath: str,
    module_prefix: str,
    language: str,
) -> List[SymbolDeclaration]:
    symbols: List[SymbolDeclaration] = []
    spec = LanguageRegistry.get_spec(language)
    node_kinds = spec.ast_node_kinds if spec and spec.ast_node_kinds else {}
    impl_types = spec.impl_node_types if spec and spec.impl_node_types else ()
    container_types = spec.container_node_types if spec and spec.container_node_types else ("Class", "Interface", "Struct", "Trait")
    has_doc_stmt = bool(spec and spec.docstring_node_type == "expression_statement")

    def visit(node: tree_sitter.Node, parent_scope: str, parent_clean: Optional[str]):
        actual_node = node
        if node.type in ("decorated_definition", "export_statement", "export_declaration"):
            for child in node.children:
                if child.type in node_kinds or any(
                    k in child.type for k in ("class", "function", "method", "interface", "struct", "enum", "trait", "type")
                ):
                    actual_node = child
                    break

        if actual_node.type in impl_types:
            type_node = actual_node.child_by_field_name("type")
            body_node = actual_node.child_by_field_name("body")
            impl_name = code_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace") if type_node else ""
            clean_impl = f"{module_prefix}.{impl_name}" if impl_name else module_prefix
            if body_node:
                for child in body_node.children:
                    visit(child, clean_impl, clean_impl)
            return

        kind = node_kinds.get(actual_node.type)
        if not kind:
            if "class" in actual_node.type:
                kind = "Class"
            elif "interface" in actual_node.type:
                kind = "Interface"
            elif "struct" in actual_node.type:
                kind = "Struct"
            elif "enum" in actual_node.type:
                kind = "Enum"
            elif "trait" in actual_node.type:
                kind = "Trait"
            elif "function" in actual_node.type or "method" in actual_node.type:
                kind = "Function"

        if kind:
            name_node = actual_node.child_by_field_name("name")
            if not name_node and actual_node.child_by_field_name("declarator"):
                decl = actual_node.child_by_field_name("declarator")
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

            if not name_node:
                for ch in actual_node.children:
                    if ch.type in ("identifier", "type_identifier"):
                        name_node = ch
                        break

            body_node = actual_node.child_by_field_name("body")
            if name_node:
                item_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                if kind in ("Function", "Method"):
                    if item_name == "__init__":
                        kind = "Constructor"
                    elif parent_clean:
                        kind = "Method"
                    else:
                        kind = "Function"

                is_callable = kind in ("Function", "Method", "Constructor")
                if is_callable:
                    clean_sym = f"{parent_scope}.{item_name}()" if parent_scope else f"{item_name}()"
                else:
                    clean_sym = f"{parent_scope}.{item_name}" if parent_scope else item_name

                sig_bytes = (
                    code_bytes[actual_node.start_byte:body_node.start_byte].strip()
                    if body_node
                    else code_bytes[actual_node.start_byte:actual_node.end_byte].strip()
                )
                if has_doc_stmt:
                    sig = sig_bytes.decode("utf-8", errors="replace")
                    doc = _extract_python_docstring(body_node, code_bytes)
                else:
                    sig = sig_bytes.decode("utf-8", errors="replace").rstrip("{").strip()
                    doc = _extract_doc_comments(actual_node, code_bytes)

                symbols.append(
                    _build_declaration(
                        node=actual_node,
                        name=item_name,
                        clean_symbol=clean_sym,
                        kind=kind,
                        filepath=filepath,
                        signature=sig,
                        docstring=doc,
                        body_node=body_node,
                        code_bytes=code_bytes,
                        parent_symbol=parent_clean,
                        language=language,
                    )
                )

                if body_node and kind in container_types:
                    scope_prefix = clean_sym[:-2] if (is_callable and clean_sym.endswith("()")) else clean_sym
                    for child in body_node.children:
                        visit(child, scope_prefix, clean_sym)
                    return

        for child in node.children:
            visit(child, parent_scope, parent_clean)

    visit(root, module_prefix, None)
    return symbols


def extract_symbols_from_file(
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
    project_root: Optional[Path] = None,
) -> List[SymbolDeclaration]:
    """Extracts symbol declarations from a source file."""
    fp = Path(filepath)
    if project_root:
        try:
            norm_fp = str(fp.resolve().relative_to(Path(project_root).resolve())).replace("\\", "/")
        except Exception:
            norm_fp = str(filepath).replace("\\", "/")
    else:
        norm_fp = str(filepath).replace("\\", "/")
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

    language = detect_language(fp)
    if not language:
        return []

    parser = get_parser(language)
    if not parser:
        return []

    tree = parser.parse(code_bytes)
    if not tree or not tree.root_node:
        return []

    return _extract_ast(tree.root_node, code_bytes, norm_fp, _derive_module_prefix(norm_fp), language)


_DI_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_DI_TYPE_ARG_RE = re.compile(r"<\s*([A-Za-z_][A-Za-z0-9_]*)")


def _find_enclosing_declaration(line: int, sorted_decls: List[SymbolDeclaration]) -> Optional[SymbolDeclaration]:
    """Finds the narrowest enclosing declaration containing the given 1-based line."""
    for decl in sorted_decls:
        if decl.start_line <= line <= decl.end_line:
            return decl
    return None


def extract_di_edges(
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
    project_root: Optional[Path] = None,
    declarations: Optional[List[SymbolDeclaration]] = None,
) -> List[Dict[str, Any]]:
    """
    Declaratively scans AST call expressions matching LanguageSpec.di_call_patterns
    and returns raw DI dependency records: {source, target_name, call_line}.
    Returns [] immediately for languages without configured di_call_patterns.
    """
    fp = Path(filepath)
    language = detect_language(fp)
    if not language:
        return []

    spec = LanguageRegistry.get_spec(language)
    if not spec or not spec.di_call_patterns:
        return []

    if source is None:
        if not fp.exists():
            return []
        code_bytes = fp.read_bytes()
    elif isinstance(source, str):
        code_bytes = source.encode("utf-8")
    else:
        code_bytes = source

    parser = get_parser(language)
    if not parser:
        return []
    tree = parser.parse(code_bytes)
    if not tree or not tree.root_node:
        return []

    decls = declarations if declarations is not None else extract_symbols_from_file(fp, code_bytes, project_root=project_root)
    if not decls:
        return []
    # Narrowest span first so inner methods win over enclosing classes
    sorted_decls = sorted(decls, key=lambda d: (d.end_line - d.start_line, d.start_line))

    patterns = spec.di_call_patterns
    pattern_regexes = [
        (pat, re.compile(rf"(?:^|[^A-Za-z0-9_]){re.escape(pat)}(?:\s*<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>)?\s*\(([^()]*)\)"))
        for pat in patterns
    ]

    di_edges: List[Dict[str, Any]] = []
    seen = set()

    def visit(node: tree_sitter.Node):
        # Match call/selector/expression nodes without hardcoding language-specific grammar names
        if "call" in node.type or "selector" in node.type or node.type in ("expression_statement", "initialized_variable_definition", "return_statement", "assignment_expression"):
            text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            for pat, regex in pattern_regexes:
                if pat not in text:
                    continue
                for match in regex.finditer(text):
                    type_arg = match.group(1)
                    arg_body = (match.group(2) or "").strip()
                    target_name = type_arg
                    if not target_name and arg_body:
                        m_type = _DI_TYPE_ARG_RE.search(arg_body)
                        if m_type:
                            target_name = m_type.group(1)
                        else:
                            first_arg = arg_body.split(",", 1)[0].strip()
                            # Strip trailing selector like .notifier or .future
                            base_arg = first_arg.split(".", 1)[0].strip()
                            m_ident = _DI_IDENT_RE.search(base_arg)
                            if m_ident:
                                target_name = m_ident.group(1)
                    if not target_name:
                        continue
                    line_offset = text[:match.start()].count("\n")
                    call_line = node.start_point.row + 1 + line_offset
                    enclosing = _find_enclosing_declaration(call_line, sorted_decls)
                    if not enclosing:
                        continue
                    key = (enclosing.symbol, target_name, call_line)
                    if key not in seen:
                        seen.add(key)
                        di_edges.append({
                            "source": enclosing.symbol,
                            "target_name": target_name,
                            "call_line": call_line,
                        })

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return di_edges
