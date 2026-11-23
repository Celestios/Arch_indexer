"""Direct cross-language interface-to-interface FFI bridge linker."""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from engines.registry import LanguageRegistry
from utils.exclusions import is_boilerplate


def parse_callable_parts(clean: str, raw_sym: str = "") -> Tuple[str, str]:
    """
    Extracts (normalized_class_name, normalized_fn_name) from symbol or clean_symbol.
    Normalizes camelCase <-> snake_case and constructors (newInstance <-> new).
    """
    text = clean or raw_sym
    base = re.sub(r"\(.*?\)", "", text).strip()

    # Rust impl: e.g. "bridge.api.impl.[AppHandle]add_anchor_spring" or "[AppHandle]::add_anchor_spring"
    rust_impl = re.search(r"\[(\w+)\](?:::)?(\w+)", base)
    if rust_impl:
        cls_name = rust_impl.group(1).lower().replace("_", "")
        fn_name = rust_impl.group(2).lower().replace("_", "")
        if fn_name in ("new", "newinstance", "create", "default"):
            fn_name = "new"
        return cls_name, fn_name

    # SCIP descriptor with hash/slash: e.g. "crate::Class#method"
    if "#" in base:
        parts = base.split("#")
        cls_part = re.split(r"[/:\\]", parts[0])[-1]
        fn_name = parts[-1].lower().replace("_", "")
        if fn_name in ("new", "newinstance", "create", "default"):
            fn_name = "new"
        return cls_part.lower().replace("_", ""), fn_name

    # Dotted identifier: e.g. "path.to.module.ClassName.methodName"
    parts = base.split(".")
    if len(parts) >= 2:
        penultimate = parts[-2]
        ultimate = parts[-1]
        if penultimate and (penultimate[0].isupper() or "_" in penultimate):
            cls_name = penultimate.lower().replace("_", "")
            fn_name = ultimate.lower().replace("_", "")
            if fn_name in ("new", "newinstance", "create", "default"):
                fn_name = "new"
            return cls_name, fn_name

    leaf = re.split(r"[/:\\]", parts[-1])[-1]
    fn_name = leaf.lower().replace("_", "")
    if fn_name in ("new", "newinstance", "create", "default"):
        fn_name = "new"
    return "", fn_name


def link_ffi_bridges(repository, config: Optional[Any] = None) -> int:
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
    by_clean: Dict[str, str] = {}
    client_symbols: List[Tuple[str, str]] = []
    native_symbols: List[Tuple[str, str]] = []

    for r in rows:
        sym = r["symbol"]
        fp = r.get("filepath") or ""
        kind = r.get("kind") or ""
        clean = r.get("clean_symbol") or sym

        if is_boilerplate(fp):
            continue

        by_id[sym] = sym
        by_clean.setdefault(clean, sym)

        is_callable = (
            kind in ("Method", "Function", "Constructor", "StaticMethod")
            or sym.endswith("()")
            or sym.endswith("().")
        )
        if not is_callable:
            continue

        ext = Path(fp.lower().replace("\\", "/")).suffix
        if ext in client_exts:
            client_symbols.append((sym, clean))
        elif ext in native_exts:
            native_symbols.append((sym, clean))

    edges_to_insert: List[Dict[str, Any]] = []
    seen_edges = set()

    # 1. Explicit config overrides (ArchConfig.ffi_bindings: client_sym -> native_sym)
    explicit_bindings: Dict[str, str] = {}
    if config is not None:
        if hasattr(config, "ffi_bindings") and isinstance(config.ffi_bindings, dict):
            explicit_bindings = config.ffi_bindings
        elif isinstance(config, dict) and isinstance(config.get("ffi_bindings"), dict):
            explicit_bindings = config["ffi_bindings"]

    for client_key, native_key in explicit_bindings.items():
        c_sym = by_id.get(client_key) or by_clean.get(client_key)
        n_sym = by_id.get(native_key) or by_clean.get(native_key)
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
    for n_sym, n_clean in native_symbols:
        native_map.setdefault(parse_callable_parts(n_clean, n_sym), []).append(n_sym)

    for c_sym, c_clean in client_symbols:
        key = parse_callable_parts(c_clean, c_sym)
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
        print(f"[Bridge Link] Created {len(edges_to_insert)} cross-language interface FFI edges.")
        return len(edges_to_insert)

    return 0
