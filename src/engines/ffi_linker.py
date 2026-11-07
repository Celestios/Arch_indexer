from dataclasses import dataclass
from typing import List

@dataclass
class FfiMatch:
    source_symbol: str
    target_symbol: str
    confidence: float
    match_type: str  # "name" or "name+signature"


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
        with self.repository.db_conn.session() as conn:
            conn.execute("DELETE FROM edges WHERE relation = 'FFI_Binds'")

    def link_scip_bridges(self) -> int:
        """
        Link high-level bridge wrappers (Dart to Rust, e.g. flutter_rust_bridge)
        based on SCIP symbol naming patterns.
        """
        with self.repository.db_conn.session() as conn:
            rows = conn.execute("SELECT symbol FROM symbols").fetchall()
            if not rows:
                return 0

            dart_symbols = []
            rust_symbols = []
            for r in rows:
                sym = r[0]
                if "crateBridgeApi" in sym and (sym.endswith("().") or sym.endswith("()")):
                    dart_symbols.append(sym)
                elif "wire__crate__" in sym and (sym.endswith("().") or sym.endswith("()")):
                    rust_symbols.append(sym)

            if not (dart_symbols and rust_symbols):
                return 0

            def clean_dart(sym):
                name = sym.split('#')[-1].replace("().", "").replace("()", "")
                return name.lower().replace("_", "")

            def clean_rust(sym):
                name = sym.split('/')[-1].replace("().", "").replace("()", "")
                if name.startswith("wire__"):
                    name = name[len("wire__"):]
                if name.endswith("_impl"):
                    name = name[:-len("_impl")]
                return name.lower().replace("_", "")

            dart_mapped = {clean_dart(d): d for d in dart_symbols}
            rust_mapped = {clean_rust(r): r for r in rust_symbols}

            edges_to_insert = []
            for k, d_sym in dart_mapped.items():
                if k in rust_mapped:
                    edges_to_insert.append({
                        "source": d_sym,
                        "target": rust_mapped[k],
                        "relation": "FFI_Binds",
                        "weight": 1.0
                    })

            if edges_to_insert:
                self.repository.edges.add_edges_bulk(edges_to_insert)
                print(f"[Bridge Link] Created {len(edges_to_insert)} cross-language bridge edges.")
                return len(edges_to_insert)
            return 0
