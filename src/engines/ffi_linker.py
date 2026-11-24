"""Direct cross-language interface-to-interface FFI bridge linker using canonical symbol IDs."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engines.registry import LanguageRegistry
from utils.arch_config import ArchConfig
from utils.exclusions import is_boilerplate
from utils.symbol_id import canonical_display_name, parse_canonical_id, strip_rust_generics

logger = logging.getLogger(__name__)


def parse_callable_parts(symbol_id: str, parent_symbol: Optional[str] = None) -> Tuple[str, str]:
    """
    Extracts (normalized_class_name, normalized_fn_name) from a canonical symbol ID.
    Normalizes camelCase <-> snake_case, strips Rust trait-impl qualifiers, ignores inline
    lowercase Rust mod scopes, and normalizes constructors (newInstance <-> new).
    """
    _, scope_parts, leaf = parse_canonical_id(symbol_id)
    if not leaf:
        return "", ""

    fn_name = leaf.lower().replace("_", "")
    if fn_name in ("new", "newinstance", "create", "default"):
        fn_name = "new"

    cls_name = ""
    if scope_parts:
        raw_scope = strip_rust_generics(scope_parts[-1])
        # Only treat scope segment as a class/type if backed by parent_symbol or PascalCase (excludes Rust inline `mod`)
        if raw_scope and (parent_symbol or raw_scope[0].isupper()):
            cls_name = raw_scope.lower().replace("_", "")

    return cls_name, fn_name


def link_ffi_bridges(repository, config: Optional[ArchConfig] = None) -> int:
    """
    Directly links client-tier API callables (e.g., Dart/TS/Python) to native-tier API
    callables (e.g., Rust/C/C++) with FFI_Binds edges, excluding generated glue code.
    Clears stale FFI_Binds edges before re-linking and applies optional config.ffi_bindings overrides first.
    """
    repository.graph.delete_edges(relation="FFI_Binds")

    rows = repository.graph.get_all_symbols()
    if not rows:
        return 0

    client_exts = LanguageRegistry.get_client_extensions()
    native_exts = LanguageRegistry.get_native_extensions()

    by_id: Dict[str, str] = {}
    by_display: Dict[str, str] = {}
    client_symbols: List[Tuple[str, Optional[str]]] = []
    native_symbols: List[Tuple[str, Optional[str]]] = []

    for r in rows:
        sym = r["symbol"]
        fp = r.get("filepath") or ""
        kind = r.get("kind") or ""
        name = r.get("name") or ""
        parent = r.get("parent_symbol")

        if is_boilerplate(fp):
            continue

        by_id[sym] = sym
        disp = canonical_display_name(sym, name)
        by_display.setdefault(disp, sym)
        if name:
            by_display.setdefault(name, sym)

        if kind not in ("Method", "Function", "Constructor", "StaticMethod"):
            continue

        ext = Path(fp.lower().replace("\\", "/")).suffix
        if ext in client_exts:
            client_symbols.append((sym, parent))
        elif ext in native_exts:
            native_symbols.append((sym, parent))

    edges_to_insert: List[Dict[str, Any]] = []
    seen_edges = set()

    # 1. Explicit config overrides (ArchConfig.ffi_bindings: client_sym -> native_sym)
    explicit_bindings: Dict[str, str] = config.ffi_bindings if config is not None else {}
    for client_key, native_key in explicit_bindings.items():
        c_sym = by_id.get(client_key) or by_display.get(client_key)
        n_sym = by_id.get(native_key) or by_display.get(native_key)
        if c_sym and n_sym and (c_sym, n_sym) not in seen_edges:
            seen_edges.add((c_sym, n_sym))
            edges_to_insert.append({
                "source": c_sym,
                "target": n_sym,
                "relation": "FFI_Binds",
                "weight": 1.0,
            })

    # 2. Direct interface-to-interface matching by normalized class/callable names
    native_map: Dict[Tuple[str, str], List[str]] = {}
    for n_sym, n_parent in native_symbols:
        native_map.setdefault(parse_callable_parts(n_sym, n_parent), []).append(n_sym)

    for c_sym, c_parent in client_symbols:
        key = parse_callable_parts(c_sym, c_parent)
        cls_name, fn_name = key
        if not fn_name:
            continue

        matched_natives = native_map.get(key, [])
        if not matched_natives and cls_name:
            matched_natives = native_map.get(("", fn_name), [])

        for n_sym in matched_natives:
            edge_key = (c_sym, n_sym)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges_to_insert.append({
                    "source": c_sym,
                    "target": n_sym,
                    "relation": "FFI_Binds",
                    "weight": 1.0,
                })

    if edges_to_insert:
        repository.graph.upsert_edges(edges_to_insert)
        logger.info("[Bridge Link] Created %d cross-language interface FFI edges.", len(edges_to_insert))
        return len(edges_to_insert)

    return 0
