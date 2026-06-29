from typing import List
from engines.ffi_matcher import FfiMatch


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
