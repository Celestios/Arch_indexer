import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

@dataclass
class FfiMatch:
    source_symbol: str
    target_symbol: str
    confidence: float
    match_type: str  # "name" or "name+signature"


def is_boilerplate(filepath: Optional[str]) -> bool:
    """Check if filepath belongs to auto-generated boilerplate code."""
    if not filepath:
        return False
    fp = filepath.replace("\\", "/").lower()
    patterns = ("generated", ".freezed.", ".g.", "frb_generated", "_impl")
    return any(p in fp for p in patterns)


def parse_callable_parts(clean: str, raw_sym: str = "") -> Tuple[str, str]:
    """
    Extracts (normalized_class_name, normalized_fn_name) from symbol or clean_symbol.
    Normalizes camelCase <-> snake_case, constructors (newInstance <-> new).
    """
    text = clean or raw_sym
    # Strip parameter list / arguments
    base = re.sub(r'\(.*?\)', '', text).strip()

    # Check for Rust impl: e.g. "bridge.api.impl.[AppHandle]add_anchor_spring" or "[AppHandle]::add_anchor_spring"
    rust_impl = re.search(r'\[(\w+)\](?:::)?(\w+)', base)
    if rust_impl:
        cls_name = rust_impl.group(1).lower().replace('_', '')
        fn_name = rust_impl.group(2).lower().replace('_', '')
        if fn_name in ('new', 'newinstance', 'create', 'default'):
            fn_name = 'new'
        return cls_name, fn_name

    # Check for SCIP descriptor with hash/slash: e.g. "crate::Class#method"
    if '#' in base:
        parts = base.split('#')
        cls_part = re.split(r'[/:\\]', parts[0])[-1]
        fn_part = parts[-1]
        fn_name = fn_part.lower().replace('_', '')
        if fn_name in ('new', 'newinstance', 'create', 'default'):
            fn_name = 'new'
        return cls_part.lower().replace('_', ''), fn_name

    # Dotted identifier: e.g. "path.to.module.ClassName.methodName"
    parts = base.split('.')
    if len(parts) >= 2:
        penultimate = parts[-2]
        ultimate = parts[-1]
        # Check if penultimate looks like a class (starts with uppercase)
        if penultimate and (penultimate[0].isupper() or '_' in penultimate):
            cls_name = penultimate.lower().replace('_', '')
            fn_name = ultimate.lower().replace('_', '')
            if fn_name in ('new', 'newinstance', 'create', 'default'):
                fn_name = 'new'
            return cls_name, fn_name

    # Free function or top-level callable
    leaf = re.split(r'[/:\\]', parts[-1])[-1]
    fn_name = leaf.lower().replace('_', '')
    if fn_name in ('new', 'newinstance', 'create', 'default'):
        fn_name = 'new'
    return "", fn_name


class FfiLinker:
    """
    Takes FFI matches and creates FFI_Binds edges in the database.
    Clears old FFI_Binds edges before re-linking to prevent stale edges.
    """

    def __init__(self, repository):
        self.repository = repository

    def link(self, matches: List[FfiMatch]) -> int:
        if not matches:
            return 0

        self._clear_old_ffi_edges()

        valid_matches = self._filter_valid_matches(matches)

        edges_to_insert = []
        for m in valid_matches:
            edges_to_insert.append({
                "source": m.source_symbol,
                "target": m.target_symbol,
                "relation": "FFI_Binds",
                "weight": m.confidence
            })

        if edges_to_insert:
            self.repository.edges.add_edges_bulk(edges_to_insert)
            print(f"[FFI Link] Created {len(edges_to_insert)} FFI_Binds edges.")

        return len(edges_to_insert)

    def _filter_valid_matches(self, matches: List[FfiMatch]) -> List[FfiMatch]:
        symbols_needed = set()
        for m in matches:
            symbols_needed.add(m.source_symbol)
            symbols_needed.add(m.target_symbol)

        with self.repository.db_conn.session() as conn:
            placeholders = ",".join(["?" for _ in symbols_needed])
            res = conn.execute(
                f"SELECT symbol FROM symbols WHERE symbol IN ({placeholders})",
                list(symbols_needed)
            ).fetchall()
            existing_symbols = {r[0] for r in res}

        return [
            m for m in matches
            if m.source_symbol in existing_symbols and m.target_symbol in existing_symbols
        ]

    def _clear_old_ffi_edges(self):
        self.repository.edges.delete_edges_by_relation("FFI_Binds")

    def link_scip_bridges(self) -> int:
        """
        Link client and native APIs across FFI bridges in a language-agnostic
        and project-agnostic manner.
        - Excludes auto-generated boilerplate code (*generated*, *.freezed.*, *.g.*).
        - Directly links client APIs (Dart/TS/JS/Python) to native APIs (Rust/C/C++).
        - Normalizes callable and class/struct names (camelCase <-> snake_case, newInstance <-> new).
        - Retains backward compatibility for legacy flutter_rust_bridge SCIP naming patterns.
        """
        with self.repository.db_conn.session() as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info('symbols')").fetchall()]
            has_clean = "clean_symbol" in cols
            query = "SELECT symbol, filepath, kind" + (", clean_symbol" if has_clean else "") + " FROM symbols"
            rows = conn.execute(query).fetchall()
            if not rows:
                return 0

            CLIENT_EXTS = {".dart", ".ts", ".tsx", ".js", ".jsx", ".py"}
            NATIVE_EXTS = {".rs", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"}

            client_symbols = []
            native_symbols = []
            legacy_dart = []
            legacy_rust = []

            for r in rows:
                sym = r[0]
                fp = r[1] or ""
                kind = r[2] or ""
                clean = r[3] if has_clean and len(r) > 3 and r[3] else sym

                # Check for legacy flutter_rust_bridge patterns
                if "crateBridgeApi" in sym and (sym.endswith("().") or sym.endswith("()")):
                    legacy_dart.append(sym)
                elif "wire__crate__" in sym and (sym.endswith("().") or sym.endswith("()")):
                    legacy_rust.append(sym)

                # Skip auto-generated boilerplate files for direct linking
                if is_boilerplate(fp):
                    continue

                is_callable = kind in ("Method", "Function", "Constructor", "StaticMethod") or sym.endswith("()") or sym.endswith("().")
                if not is_callable:
                    continue

                fp_lower = fp.lower().replace("\\", "/")
                ext = Path(fp_lower).suffix

                if ext in CLIENT_EXTS:
                    client_symbols.append((sym, clean, fp, kind))
                elif ext in NATIVE_EXTS:
                    native_symbols.append((sym, clean, fp, kind))

            edges_to_insert = []
            seen_edges = set()

            # 1. Direct API Linking: Match class/struct names and callable names
            native_map: Dict[Tuple[str, str], List[Tuple[str, str, str, str]]] = {}
            for n_sym, n_clean, n_fp, n_kind in native_symbols:
                key = parse_callable_parts(n_clean, n_sym)
                native_map.setdefault(key, []).append((n_sym, n_clean, n_fp, n_kind))

            for c_sym, c_clean, c_fp, c_kind in client_symbols:
                key = parse_callable_parts(c_clean, c_sym)
                cls_name, fn_name = key
                if not fn_name:
                    continue

                matched_natives = native_map.get(key, [])
                if not matched_natives and cls_name:
                    matched_natives = native_map.get(("", fn_name), [])

                for n_sym, n_clean, n_fp, n_kind in matched_natives:
                    edge_key = (c_sym, n_sym)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges_to_insert.append({
                            "source": c_sym,
                            "target": n_sym,
                            "relation": "FFI_Binds",
                            "weight": 1.0
                        })

            # 2. Legacy fallback for generated bridges
            if legacy_dart and legacy_rust:
                def clean_dart(s):
                    name = s.split('#')[-1].replace("().", "").replace("()", "")
                    return name.lower().replace("_", "")

                def clean_rust(s):
                    name = s.split('/')[-1].replace("().", "").replace("()", "")
                    if name.startswith("wire__"):
                        name = name[len("wire__"):]
                    if name.endswith("_impl"):
                        name = name[:-len("_impl")]
                    return name.lower().replace("_", "")

                dart_mapped = {clean_dart(d): d for d in legacy_dart}
                rust_mapped = {clean_rust(r): r for r in legacy_rust}

                for k, d_sym in dart_mapped.items():
                    if k in rust_mapped:
                        r_sym = rust_mapped[k]
                        edge_key = (d_sym, r_sym)
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            edges_to_insert.append({
                                "source": d_sym,
                                "target": r_sym,
                                "relation": "FFI_Binds",
                                "weight": 1.0
                            })

            if edges_to_insert:
                self.repository.edges.add_edges_bulk(edges_to_insert)
                print(f"[Bridge Link] Created {len(edges_to_insert)} cross-language bridge edges.")
                return len(edges_to_insert)

            return 0
