"""Tree-sitter AST canonical symbol declaration extractor."""
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import tree_sitter

from engines.registry import LanguageRegistry
from engines.treesitter.annotations import extract_annotations
from engines.treesitter.loader import detect_language, get_parser
from engines.treesitter.metrics import calculate_metrics
from utils.symbol_id import (
    build_canonical_id,
    format_dart_leaf_name,
    format_rust_impl_scope,
    normalize_symbol_path,
    strip_rust_generics,
)


class SymbolDeclaration:
    """Represents a canonical symbol declaration extracted via Tree-sitter AST."""

    def __init__(
        self,
        name: str,
        symbol: str,
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
        self.symbol = symbol
        self.kind = kind
        self.filepath = normalize_symbol_path(filepath) or filepath
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
            "name": self.name,
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


def _collect_local_rust_types(root: tree_sitter.Node, code_bytes: bytes) -> Set[Tuple[Tuple[str, ...], str]]:
    """Pre-scans a Rust AST for locally declared types so cross-file impl blocks never fabricate ghost parents."""
    declared: Set[Tuple[Tuple[str, ...], str]] = set()

    def walk(node: tree_sitter.Node, scope: Tuple[str, ...]):
        if node.type == "mod_item":
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            if name_node and body_node:
                mod_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                walk(body_node, scope + (mod_name,))
            return
        if node.type in ("struct_item", "enum_item", "trait_item", "type_item"):
            name_node = node.child_by_field_name("name")
            if name_node:
                t_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                declared.add((scope, t_name))
        for ch in node.children:
            walk(ch, scope)

    walk(root, ())
    return declared


def _extract_dart_constructor_name(
    node: tree_sitter.Node,
    code_bytes: bytes,
    scope_chain: List[str],
) -> Optional[str]:
    """Extracts Dart constructor leaf name: 'new' for unnamed, or '<named>' for ClassName.<named>."""
    ctor_node = node
    if node.type != "constructor_signature":
        for ch in node.children:
            if ch.type == "constructor_signature":
                ctor_node = ch
                break

    ident_parts: List[str] = []
    for ch in ctor_node.children:
        if ch.type == "identifier":
            ident_parts.append(code_bytes[ch.start_byte:ch.end_byte].decode("utf-8", errors="replace"))
        elif ch.type == "formal_parameter_list":
            break

    if not ident_parts:
        name_node = ctor_node.child_by_field_name("name")
        if name_node:
            raw = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
            ident_parts = [p for p in raw.split(".") if p]

    if not ident_parts:
        return None
    if len(ident_parts) >= 2:
        return ident_parts[-1]
    single = ident_parts[0]
    if scope_chain and single == scope_chain[-1]:
        return "new"
    return single


def _build_declaration(
    node: tree_sitter.Node,
    name: str,
    symbol: str,
    kind: str,
    filepath: str,
    signature: str,
    docstring: str,
    body_node: Optional[tree_sitter.Node],
    code_bytes: bytes,
    parent_symbol: Optional[str],
    language: str,
    end_point: Optional[Tuple[int, int]] = None,
) -> SymbolDeclaration:
    body_bytes = code_bytes[body_node.start_byte:body_node.end_byte] if body_node else b""
    b_hash = hashlib.sha256(body_bytes).hexdigest()[:16]
    annotations = extract_annotations(node, code_bytes, language)
    target_metric_node = body_node if body_node else node
    metrics = calculate_metrics(target_metric_node, code_bytes)

    end_row = (end_point[0] if end_point else node.end_point.row) + 1
    end_col = end_point[1] if end_point else node.end_point.column

    return SymbolDeclaration(
        name=name,
        symbol=symbol,
        kind=kind,
        filepath=filepath,
        start_line=node.start_point.row + 1,
        start_col=node.start_point.column,
        end_line=end_row,
        end_col=end_col,
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
    language: str,
) -> List[SymbolDeclaration]:
    symbols: List[SymbolDeclaration] = []
    spec = LanguageRegistry.get_spec(language)
    node_kinds = spec.ast_node_kinds if spec and spec.ast_node_kinds else {}
    impl_types = spec.impl_node_types if spec and spec.impl_node_types else ()
    container_types = spec.container_node_types if spec and spec.container_node_types else ("Class", "Interface", "Struct", "Trait")
    has_doc_stmt = bool(spec and spec.docstring_node_type == "expression_statement")
    norm_filepath = normalize_symbol_path(filepath) or filepath
    local_rust_types = _collect_local_rust_types(root, code_bytes) if language == "rust" else set()

    def visit(
        node: tree_sitter.Node,
        scope_chain: List[str],
        parent_id: Optional[str],
        body_override: Optional[tree_sitter.Node] = None,
    ):
        actual_node = node
        if node.type in ("decorated_definition", "export_statement", "export_declaration"):
            for child in node.children:
                if child.type in node_kinds or any(
                    k in child.type for k in ("class", "function", "method", "interface", "struct", "enum", "trait", "type")
                ):
                    actual_node = child
                    break

        # Rust impl_item handling: scope methods under Type or Type<Trait>; only set parent_symbol if Type is local
        if actual_node.type in impl_types:
            type_node = actual_node.child_by_field_name("type")
            trait_node = actual_node.child_by_field_name("trait")
            body_node = actual_node.child_by_field_name("body")
            impl_name = code_bytes[type_node.start_byte:type_node.end_byte].decode("utf-8", errors="replace") if type_node else ""
            trait_name = code_bytes[trait_node.start_byte:trait_node.end_byte].decode("utf-8", errors="replace") if trait_node else None

            target_type = strip_rust_generics(impl_name)
            scope_segment = format_rust_impl_scope(target_type, trait_name)
            if target_type and (tuple(scope_chain), target_type) in local_rust_types:
                impl_parent_id: Optional[str] = build_canonical_id(
                    filepath=norm_filepath,
                    scope_chain=scope_chain,
                    name=target_type,
                )
            else:
                impl_parent_id = None
            if body_node and scope_segment:
                _visit_children(body_node, scope_chain + [scope_segment], impl_parent_id)
            return

        # Rust mod_item handling: preserve inline module hierarchy
        if actual_node.type == "mod_item":
            name_node = actual_node.child_by_field_name("name")
            body_node = actual_node.child_by_field_name("body")
            if name_node and body_node:
                mod_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                _visit_children(body_node, scope_chain + [mod_name], parent_id)
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
            dart_sub_kind = None
            if actual_node.type == "getter_signature" or any(ch.type == "getter_signature" for ch in actual_node.children):
                dart_sub_kind = "Getter"
            elif actual_node.type == "setter_signature" or any(ch.type == "setter_signature" for ch in actual_node.children):
                dart_sub_kind = "Setter"
            elif actual_node.type == "constructor_signature" or any(ch.type == "constructor_signature" for ch in actual_node.children):
                dart_sub_kind = "Constructor"

            item_name: Optional[str] = None
            if dart_sub_kind == "Constructor":
                kind = "Constructor"
                item_name = _extract_dart_constructor_name(actual_node, code_bytes, scope_chain)
            else:
                name_node = actual_node.child_by_field_name("name")
                if not name_node:
                    for ch in actual_node.children:
                        if ch.type in ("function_signature", "getter_signature", "setter_signature"):
                            inner_name = ch.child_by_field_name("name")
                            if inner_name:
                                name_node = inner_name
                                break
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

                if name_node:
                    item_name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")

            body_node = body_override if body_override is not None else actual_node.child_by_field_name("body")
            if body_node is None and actual_node.type in ("extension_declaration", "mixin_declaration"):
                for ch in actual_node.children:
                    if ch.type in ("extension_body", "class_body"):
                        body_node = ch
                        break

            end_point = body_node.end_point if body_override is not None else None
            if item_name:
                if dart_sub_kind == "Getter":
                    kind = "Getter"
                    item_name = format_dart_leaf_name(item_name, "Getter")
                elif dart_sub_kind == "Setter":
                    kind = "Setter"
                    item_name = format_dart_leaf_name(item_name, "Setter")
                elif dart_sub_kind == "Constructor":
                    item_name = format_dart_leaf_name(item_name, "Constructor")
                elif kind in ("Function", "Method"):
                    if item_name == "__init__":
                        kind = "Constructor"
                    elif parent_id or (language == "rust" and scope_chain):
                        kind = "Method"
                    else:
                        kind = "Function"

                canonical_id = build_canonical_id(
                    filepath=norm_filepath,
                    scope_chain=scope_chain,
                    name=item_name,
                )

                is_callable = kind in ("Function", "Method", "Constructor", "Getter", "Setter")

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
                        symbol=canonical_id,
                        kind=kind,
                        filepath=norm_filepath,
                        signature=sig,
                        docstring=doc,
                        body_node=body_node,
                        code_bytes=code_bytes,
                        parent_symbol=parent_id,
                        language=language,
                        end_point=end_point,
                    )
                )

                if body_node and kind in container_types:
                    _visit_children(body_node, scope_chain + [item_name], canonical_id)
                    return
                if is_callable:
                    return

        _visit_children(node, scope_chain, parent_id)

    def _visit_children(parent: tree_sitter.Node, s_chain: List[str], p_id: Optional[str]):
        children = parent.children
        i = 0
        n_children = len(children)
        while i < n_children:
            ch = children[i]
            if ch.type in ("method_signature", "function_signature", "constructor_signature", "getter_signature", "setter_signature"):
                next_body = None
                j = i + 1
                while j < n_children:
                    next_ch = children[j]
                    if next_ch.type in ("comment", "line_comment", "block_comment"):
                        j += 1
                        continue
                    if next_ch.type == "function_body":
                        next_body = next_ch
                    break
                if next_body is not None:
                    visit(ch, s_chain, p_id, body_override=next_body)
                    i = j + 1
                    continue

            visit(ch, s_chain, p_id)
            i += 1

    visit(root, [], None)
    return symbols


def extract_symbols_from_file(
    filepath: Union[str, Path],
    source: Optional[Union[str, bytes]] = None,
    project_root: Optional[Path] = None,
) -> List[SymbolDeclaration]:
    """Extracts canonical symbol declarations from a source file."""
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

    return _extract_ast(tree.root_node, code_bytes, norm_fp, language)


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
    sorted_decls = sorted(decls, key=lambda d: (d.end_line - d.start_line, d.start_line))

    patterns = spec.di_call_patterns
    pattern_regexes = [
        (pat, re.compile(rf"(?:^|[^A-Za-z0-9_]){re.escape(pat)}(?:\s*<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>)?\s*\(([^()]*)\)"))
        for pat in patterns
    ]

    di_edges: List[Dict[str, Any]] = []
    seen = set()

    def visit(node: tree_sitter.Node):
        if "call" in node.type or "selector" in node.type or node.type in (
            "expression_statement",
            "initialized_variable_definition",
            "return_statement",
            "assignment_expression",
        ):
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
