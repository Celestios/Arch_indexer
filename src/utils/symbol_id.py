"""
Single Source of Truth Canonical Symbol Identity Architecture.
Canonical ID format:
  - Workspace: <posix_filepath>::<ScopeChain>::<disambiguated_name>
  - External:  ext::<manager>/<package>::<ScopeChain>::<name>
"""
import re
from pathlib import PurePosixPath
from typing import List, Optional, Tuple


def normalize_symbol_path(filepath: Optional[str]) -> Optional[str]:
    """Canonical POSIX path normalization for symbol identifiers."""
    if not filepath:
        return None
    p = filepath.replace("\\", "/").strip()
    p = re.sub(r"^[a-zA-Z]:/*", "", p)
    while p.startswith("./") or p.startswith("/"):
        p = p[2:] if p.startswith("./") else p[1:]
    return p


def strip_rust_generics(type_str: str) -> str:
    """Strips Rust generic parameters (e.g. 'Foo<T, U>' -> 'Foo', 'impl<T> Bar<T>' -> 'Bar')."""
    if not type_str:
        return ""
    s = type_str.strip()
    if s.startswith("impl"):
        s = re.sub(r"^impl\s*(<[^>]*>)?\s*", "", s).strip()
    while "<" in s and ">" in s:
        s = re.sub(r"<[^<>]*>", "", s).strip()
    return s.strip()


def format_rust_impl_scope(target_type: str, trait_name: Optional[str] = None) -> str:
    """Formats Rust impl scope: 'Foo' or 'Foo<Display>' for trait implementations."""
    clean_target = strip_rust_generics(target_type)
    if trait_name:
        clean_trait = strip_rust_generics(trait_name)
        return f"{clean_target}<{clean_trait}>"
    return clean_target


def format_dart_leaf_name(raw_name: str, kind: str) -> str:
    """Disambiguates Dart getters, setters, and constructors."""
    clean = raw_name.strip()
    if kind == "Getter":
        return clean if clean.startswith("get:") else f"get:{clean}"
    if kind == "Setter":
        clean = clean.rstrip("=")
        return clean if clean.startswith("set:") else f"set:{clean}"
    if kind == "Constructor":
        if not clean or clean in ("new", "<constructor>"):
            return "new"
        if "." in clean:
            return clean.split(".")[-1]
        return clean
    return clean


def build_canonical_id(
    filepath: Optional[str] = None,
    scope_chain: Optional[List[str]] = None,
    name: str = "",
    manager: Optional[str] = None,
    package: Optional[str] = None,
) -> str:
    """
    Builds canonical disambiguated symbol primary key:
      Workspace: <posix_filepath>::<Scope1>::<Scope2>::<name>
      External:  ext::<manager>/<package>::<Scope1>::<name>
    """
    segments: List[str] = []
    norm_fp = normalize_symbol_path(filepath)

    if norm_fp:
        segments.append(norm_fp)
    else:
        mgr = manager or "pkg"
        pkg = package or "unknown"
        segments.append(f"ext::{mgr}/{pkg}")

    if scope_chain:
        for s in scope_chain:
            s_clean = s.strip()
            if s_clean:
                segments.append(s_clean)

    if name:
        segments.append(name.strip())

    return "::".join(segments)


def parse_canonical_id(symbol_id: str) -> Tuple[Optional[str], List[str], str]:
    """
    Deconstructs canonical ID into (filepath_or_pkg_prefix, scope_parts, leaf_name).
    Example: 'lib/foo.dart::Class::method' -> ('lib/foo.dart', ['Class'], 'method')
             'lib/foo.dart::top_level'     -> ('lib/foo.dart', [], 'top_level')
             'ext::pub/flutter::Widget'    -> ('ext::pub/flutter', [], 'Widget')
    """
    if not symbol_id:
        return None, [], ""

    if symbol_id.startswith("ext::"):
        rest = symbol_id[5:]
        parts = rest.split("::")
        pkg_prefix = f"ext::{parts[0]}"
        if len(parts) == 1:
            return pkg_prefix, [], ""
        return pkg_prefix, parts[1:-1], parts[-1]

    parts = symbol_id.split("::")
    filepath = parts[0]
    if len(parts) == 1:
        return filepath, [], filepath
    return filepath, parts[1:-1], parts[-1]


def canonical_display_name(symbol_id: str, name: Optional[str] = None) -> str:
    """
    Returns short, clean display name from canonical ID:
      Top-level: 'func'
      Member:    'Parent::method'
    """
    if not symbol_id:
        return name or ""
    _, scope_parts, leaf = parse_canonical_id(symbol_id)
    if not leaf:
        return name or symbol_id
    if scope_parts:
        return f"{scope_parts[-1]}::{leaf}"
    return leaf


def parse_scip_descriptors(desc_str: str) -> List[Tuple[str, str]]:
    """
    Parses a SCIP descriptor string into a list of (name, suffix) tuples.
    Handles backtick-escaped names, method/type-parameter suffixes, and Rust bracketed trait impls.
    """
    descriptors: List[Tuple[str, str]] = []
    i = 0
    n = len(desc_str)
    while i < n:
        if desc_str[i] == "[":
            end_br = desc_str.find("]", i + 1)
            if end_br != -1:
                descriptors.append((desc_str[i + 1:end_br], "[]"))
                i = end_br + 1
                continue

        if desc_str[i] == "`":
            end_bt = desc_str.find("`", i + 1)
            if end_bt != -1:
                name = desc_str[i + 1:end_bt]
                i = end_bt + 1
            else:
                name = desc_str[i + 1:]
                i = n
        else:
            start = i
            while i < n and desc_str[i] not in ("/", "#", ".", ":", "!", "(", "["):
                i += 1
            name = desc_str[start:i]

        suffix = ""
        if i < n:
            ch = desc_str[i]
            if ch in ("/", "#", ":", "!", "."):
                suffix = ch
                i += 1
            elif ch == "(":
                end_p = desc_str.find(")", i)
                if end_p != -1:
                    suffix = desc_str[i:end_p + 1]
                    i = end_p + 1
                    if i < n and desc_str[i] == ".":
                        suffix += "."
                        i += 1
                else:
                    suffix = "("
                    i += 1

        if name or suffix:
            descriptors.append((name, suffix))
    return descriptors


def _collapse_rust_impl_tokens(tokens: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Normalizes rust-analyzer bracketed trait-impl descriptors into canonical <Type><Trait> scope tokens."""
    out: List[Tuple[str, str]] = []
    i = 0
    n = len(tokens)
    while i < n:
        val, suff = tokens[i]
        # Pattern 1: ('impl', '#'), (Type, '[]'), (Trait, '[]')
        if val == "impl" and suff == "#" and i + 2 < n and tokens[i + 1][1] == "[]" and tokens[i + 2][1] == "[]":
            out.append((format_rust_impl_scope(tokens[i + 1][0], tokens[i + 2][0]), "#"))
            i += 3
            continue
        # Pattern 2: ('impl', '#'), (Type, '[]')
        if val == "impl" and suff == "#" and i + 1 < n and tokens[i + 1][1] == "[]":
            out.append((format_rust_impl_scope(tokens[i + 1][0]), "#"))
            i += 2
            continue
        # Pattern 3: (Type, '#'), (Trait, '[]')
        if suff == "#" and i + 1 < n and tokens[i + 1][1] == "[]":
            out.append((format_rust_impl_scope(val, tokens[i + 1][0]), "#"))
            i += 2
            continue
        out.append((val, suff))
        i += 1
    return out


def _strip_leading_file_module_tokens(
    tokens: List[Tuple[str, str]],
    norm_filepath: str,
) -> List[Tuple[str, str]]:
    """
    Strips leading SCIP namespace ('/') tokens that correspond to the file's own directory/module path
    while preserving genuine inline module scopes (e.g., Rust `mod inner { ... }`).
    """
    posix = PurePosixPath(norm_filepath)
    filename = posix.name
    stem = posix.stem
    dir_parts = list(posix.parts[:-1])
    file_mod_parts = dir_parts + [stem]

    idx = 0
    n = len(tokens)
    # 1. Strip direct filepath / filename tokens (Dart, TS)
    while idx < n - 1 and tokens[idx][1] == "/":
        val = tokens[idx][0]
        norm_val = normalize_symbol_path(val) or val
        if (
            norm_val == norm_filepath
            or norm_val == filename
            or norm_filepath.endswith("/" + norm_val)
            or "/" in val
            or "\\" in val
            or "." in val
        ):
            idx += 1
        else:
            break

    # 2. Match leading namespace segments greedily against file_mod_parts (Python, Rust)
    cursor = 0
    while idx < n - 1 and tokens[idx][1] == "/":
        seg = tokens[idx][0]
        found_at = -1
        for j in range(cursor, len(file_mod_parts)):
            if file_mod_parts[j] == seg:
                found_at = j
                break
        if found_at != -1:
            cursor = found_at + 1
            idx += 1
        else:
            break

    return tokens[idx:] if idx < n else tokens


def scip_to_canonical_id(
    raw_scip: str,
    resolved_filepath: Optional[str] = None,
    kind: Optional[str] = None,
) -> Tuple[str, str, Optional[str]]:
    """
    Translates a raw SCIP symbol string into canonical (symbol_id, leaf_name, parent_canonical_id).
    Strictly isolated to SCIP parsing ingress.
    Any symbol with a resolved_filepath is treated as a workspace symbol regardless of SCIP manager/package.
    """
    if not raw_scip or raw_scip.startswith("local "):
        return raw_scip or "", raw_scip or "", None

    parts = raw_scip.split(" ", 4)
    if len(parts) < 5:
        return raw_scip, raw_scip, None

    scheme, manager, package, _version, desc_str = parts
    norm_fp = normalize_symbol_path(resolved_filepath) if resolved_filepath else None
    is_workspace = norm_fp is not None

    if is_workspace and norm_fp:
        filename = norm_fp.split("/")[-1] if "/" in norm_fp else norm_fp
        for pfx in (f"`{norm_fp}`/", f"{norm_fp}/", f"`{filename}`/", f"{filename}/"):
            if desc_str.startswith(pfx):
                desc_str = desc_str[len(pfx):]
                break

    tokens = _collapse_rust_impl_tokens(parse_scip_descriptors(desc_str))
    if not tokens:
        return raw_scip, raw_scip, None

    if is_workspace and norm_fp:
        filtered_tokens = _strip_leading_file_module_tokens(tokens, norm_fp)
    else:
        filtered_tokens = tokens

    scope_tokens = filtered_tokens[:-1]
    scope_chain: List[str] = []
    for val, _suff in scope_tokens:
        clean_v = val.strip() if "<" in val and ">" in val else strip_rust_generics(val)
        if clean_v:
            scope_chain.append(clean_v)

    leaf_val, _leaf_suff = filtered_tokens[-1]
    leaf_clean = leaf_val.strip()

    # Disambiguate Dart getters, setters, and constructors symmetrically with Tree-sitter
    is_dart = (norm_fp and norm_fp.endswith(".dart")) or scheme == "scip-dart"
    if is_dart:
        if kind == "Getter" or leaf_clean.startswith("get:"):
            leaf_clean = format_dart_leaf_name(leaf_clean, "Getter")
        elif kind == "Setter" or leaf_clean.startswith("set:") or leaf_clean.endswith("="):
            leaf_clean = format_dart_leaf_name(leaf_clean, "Setter")
        elif kind == "Constructor" or leaf_clean in ("new", "<constructor>"):
            if scope_chain and leaf_clean == scope_chain[-1]:
                leaf_clean = "new"
            else:
                leaf_clean = format_dart_leaf_name(leaf_clean, "Constructor")

    canonical_id = build_canonical_id(
        filepath=norm_fp if is_workspace else None,
        scope_chain=scope_chain,
        name=leaf_clean,
        manager=manager if not is_workspace else None,
        package=package if not is_workspace else None,
    )

    # Derive parent container ID only when the immediate enclosing descriptor is a Type/Impl (#), not a module (/)
    parent_canonical_id: Optional[str] = None
    if scope_tokens and scope_tokens[-1][1] == "#":
        parent_leaf = strip_rust_generics(scope_chain[-1])
        parent_canonical_id = build_canonical_id(
            filepath=norm_fp if is_workspace else None,
            scope_chain=scope_chain[:-1],
            name=parent_leaf,
            manager=manager if not is_workspace else None,
            package=package if not is_workspace else None,
        )

    return canonical_id, leaf_clean, parent_canonical_id
