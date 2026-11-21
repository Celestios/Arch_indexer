import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from db.base import (
    BaseRepository,
    UPSERT_SYNTACTIC_SYMBOL_SQL,
    UPSERT_SEMANTIC_SYMBOL_SQL,
    UPSERT_EDGE_SQL,
    normalize_path,
)
from utils.helpers import demangle_scip_symbol

logger = logging.getLogger(__name__)

_SYMBOL_COLS = """
    symbol, filepath, kind, signature, docstring, body_hash, connection_weight,
    parent_symbol, classification, change_count, clean_symbol,
    start_line, start_col, end_line, end_col
"""


class GraphStore(BaseRepository):
    """
    Domain store owning symbols, edges, and reference occurrences.
    Enforces POSIX path normalization on ingress and disjoint Tier-1/Tier-2 symbol upserts.
    """

    @staticmethod
    def _format_symbol_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        res = dict(row)
        if res.get("filepath"):
            res["filepath"] = normalize_path(res["filepath"])
        if not res.get("clean_symbol") and res.get("symbol"):
            res["clean_symbol"] = demangle_scip_symbol(res["symbol"])
        return res

    @staticmethod
    def _build_symbol_tuples(symbols_list: List[Dict[str, Any]]) -> List[tuple]:
        return [
            (
                sym["symbol"],
                sym.get("clean_symbol") or demangle_scip_symbol(sym["symbol"]),
                normalize_path(sym.get("filepath")),
                sym["kind"],
                sym.get("signature"),
                sym.get("docstring"),
                sym.get("body_hash"),
                sym.get("connection_weight", 0),
                sym.get("parent_symbol"),
                sym.get("start_line"),
                sym.get("start_col"),
                sym.get("end_line"),
                sym.get("end_col"),
            )
            for sym in symbols_list
        ]

    # ------------------ Symbols Domain ------------------

    def upsert_syntactic_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Tier-1 (Tree-sitter) bulk upsert owning syntactic columns and declaration coordinates."""
        if not symbols_list:
            return
        self._executemany(UPSERT_SYNTACTIC_SYMBOL_SQL, self._build_symbol_tuples(symbols_list))

    def upsert_semantic_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Tier-2 (SCIP) bulk upsert preserving Tier-1 syntactic columns and populating SCIP-only symbols."""
        if not symbols_list:
            return
        self._executemany(UPSERT_SEMANTIC_SYMBOL_SQL, self._build_symbol_tuples(symbols_list))

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a registered symbol declaration by ID or clean_symbol."""
        row = self._fetch_one(
            f"SELECT {_SYMBOL_COLS} FROM symbols WHERE symbol = ? OR clean_symbol = ?",
            (symbol, symbol),
        )
        return self._format_symbol_dict(row)

    def get_symbols_for_files(self, filepaths: List[str]) -> List[Dict[str, Any]]:
        """Retrieves all symbols declared across the given filepaths."""
        if not filepaths:
            return []
        fps = [normalize_path(fp) for fp in filepaths if fp]
        if not fps:
            return []
        rows = self._fetch_all(
            f"SELECT {_SYMBOL_COLS} FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
            (fps,),
        )
        return [self._format_symbol_dict(r) for r in rows if r]

    def get_symbols_by_ids(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch-fetches symbol records keyed by symbol ID."""
        if not symbols:
            return {}
        rows = self._fetch_all(
            f"SELECT {_SYMBOL_COLS} FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
            (list(symbols),),
        )
        return {r["symbol"]: self._format_symbol_dict(r) for r in rows if r}

    def get_all_symbols(self) -> List[Dict[str, Any]]:
        """Retrieves all symbols in the workspace."""
        rows = self._fetch_all(f"SELECT {_SYMBOL_COLS} FROM symbols")
        return [self._format_symbol_dict(r) for r in rows if r]

    def get_member_symbols(self, parent_symbol: str) -> List[Dict[str, Any]]:
        """Retrieves member methods and constructors belonging to a class symbol."""
        prefix = parent_symbol if parent_symbol.endswith("#") else parent_symbol + "#"
        return self._fetch_all(
            """SELECT symbol, kind, signature, docstring FROM symbols
               WHERE parent_symbol = ?
                  OR (symbol LIKE ? AND (kind IN ('Method', 'Constructor') OR symbol LIKE '%().'))
               ORDER BY symbol""",
            (parent_symbol, prefix + "%"),
        )

    def search_symbols(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Case-insensitive substring search over clean_symbol and symbol."""
        pattern = f"%{query}%"
        rows = self._fetch_all(
            f"""SELECT {_SYMBOL_COLS} FROM symbols
                WHERE LOWER(clean_symbol) LIKE LOWER(?) OR LOWER(symbol) LIKE LOWER(?)
                LIMIT ?""",
            (pattern, pattern, limit),
        )
        return [self._format_symbol_dict(r) for r in rows if r]

    def update_symbols_classification(self, classifications: Dict[str, Dict[str, Any]]):
        """Batch update of symbol classification JSON strings."""
        if not classifications:
            return
        data = [(json.dumps(val), sym) for sym, val in classifications.items()]
        self._executemany("UPDATE symbols SET classification = ? WHERE symbol = ?", data)

    def recalculate_connection_weights(self):
        """Recomputes connection_weight for each symbol from incoming and outgoing edge counts."""
        self._execute("UPDATE symbols SET connection_weight = 0")
        self._execute("""
            UPDATE symbols
            SET connection_weight = COALESCE(e_in.cnt, 0) + COALESCE(e_out.cnt, 0)
            FROM (
                SELECT target AS sym, COUNT(*) AS cnt FROM edges GROUP BY target
            ) e_in FULL OUTER JOIN (
                SELECT source AS sym, COUNT(*) AS cnt FROM edges GROUP BY source
            ) e_out ON e_in.sym = e_out.sym
            WHERE symbols.symbol = COALESCE(e_in.sym, e_out.sym)
        """)

    def delete_symbols(
        self,
        symbols: Optional[List[str]] = None,
        filepaths: Optional[List[str]] = None,
    ):
        """Deletes symbols matching explicit IDs and/or filepaths."""
        if symbols:
            self._execute(
                "DELETE FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
                (list(symbols),),
            )
        if filepaths:
            self._delete_by_filepaths("symbols", filepaths)

    # ------------------ Edges Domain ------------------

    def upsert_edges(self, edges_list: List[Dict[str, Any]]):
        """Bulk inserts or updates edges."""
        if not edges_list:
            return
        data = [
            (
                e["source"],
                e["target"],
                e.get("relation", "Calls"),
                float(e.get("weight", 1.0)),
                e.get("call_line") or e.get("line"),
            )
            for e in edges_list
        ]
        self._executemany(UPSERT_EDGE_SQL, data)

    def get_edges(
        self,
        source: Optional[str] = None,
        target: Optional[str] = None,
        targets: Optional[List[str]] = None,
        symbol: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Queries edges matching optional source, target(s), incident symbol, or relation filters."""
        query = "SELECT source, target, relation, weight, call_line FROM edges WHERE 1=1"
        params: List[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if target:
            query += " AND target = ?"
            params.append(target)
        if targets is not None:
            if not targets:
                return []
            query += " AND target IN (SELECT UNNEST(?::VARCHAR[]))"
            params.append(list(targets))
        if symbol:
            query += " AND (source = ? OR target = ?)"
            params.extend([symbol, symbol])
        if relation:
            query += " AND relation = ?"
            params.append(relation)
        return self._fetch_all(query, params)

    def get_edges_with_locations(self) -> List[Dict[str, Any]]:
        """Returns edges enriched with call-site line/col coordinates."""
        return self._fetch_all(
            """
            SELECT e.source, e.target, e.relation, e.weight,
                   COALESCE(e.call_line, o.start_line) AS line, o.start_col AS col
            FROM edges e
            LEFT JOIN symbols s ON e.source = s.symbol
            LEFT JOIN occurrences o ON e.target = o.symbol AND s.filepath = o.filepath
            """
        )

    def get_dependent_files(self, filepaths: List[str]) -> List[str]:
        """Finds files containing symbols that depend on the given files."""
        if not filepaths:
            return []
        fps = [normalize_path(fp) for fp in filepaths if fp]
        if not fps:
            return []
        rows = self._fetch_all(
            """SELECT DISTINCT s_src.filepath
               FROM edges e
               JOIN symbols s_src ON e.source = s_src.symbol
               JOIN symbols s_tgt ON e.target = s_tgt.symbol
               WHERE s_tgt.filepath IN (SELECT UNNEST(?::VARCHAR[]))
                 AND s_src.filepath NOT IN (SELECT UNNEST(?::VARCHAR[]))
                 AND s_src.filepath IS NOT NULL""",
            (fps, fps),
        )
        return [normalize_path(r["filepath"]) for r in rows if r.get("filepath")]

    def update_edge_weights(self, weight_updates: List[tuple]):
        """Batch update edge weights: list of (weight, source, target, relation)."""
        if not weight_updates:
            return
        self._executemany(
            "UPDATE edges SET weight = ? WHERE source = ? AND target = ? AND relation = ?",
            weight_updates,
        )

    def delete_edges(
        self,
        relation: Optional[str] = None,
        filepaths: Optional[List[str]] = None,
    ):
        """Deletes edges matching a relation type and/or touching symbols in filepaths."""
        if relation:
            self._execute("DELETE FROM edges WHERE relation = ?", (relation,))
        if filepaths:
            fps = [normalize_path(fp) for fp in filepaths if fp]
            if fps:
                self._execute(
                    """DELETE FROM edges
                       WHERE source IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))
                          OR target IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))""",
                    (fps, fps),
                )

    # ------------------ Occurrences & Hygiene Domain ------------------

    def upsert_occurrences(self, occurrences_list: List[Dict[str, Any]]):
        """Bulk inserts reference occurrences."""
        if not occurrences_list:
            return
        data = [
            (
                occ["symbol"],
                normalize_path(occ["filepath"]),
                occ["start_line"],
                occ["start_col"],
                occ["end_line"],
                occ["end_col"],
                occ["role"],
            )
            for occ in occurrences_list
        ]
        self._executemany(
            "INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
            data,
        )

    def get_occurrences(
        self,
        symbol: Optional[str] = None,
        filepath: Optional[str] = None,
        filepath_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Queries occurrences matching optional symbol, exact filepath, or filepath substring."""
        query = "SELECT symbol, filepath, start_line, start_col, end_line, end_col, role FROM occurrences WHERE 1=1"
        params: List[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if filepath:
            query += " AND filepath = ?"
            params.append(normalize_path(filepath))
        if filepath_filter:
            query += " AND filepath LIKE ?"
            params.append(f"%{normalize_path(filepath_filter)}%")
        query += " ORDER BY filepath, start_line, start_col"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = self._fetch_all(query, params)
        for r in rows:
            r["filepath"] = normalize_path(r.get("filepath"))
        return rows

    def delete_occurrences(self, filepaths: List[str]):
        """Deletes occurrences in the given files."""
        self._delete_by_filepaths("occurrences", filepaths)

    def delete_orphaned_records(self) -> Tuple[int, int]:
        """Deletes edges and occurrences whose symbols no longer exist. Returns (edges_deleted, occs_deleted)."""
        edge_row = self._fetch_one("""
            SELECT COUNT(*) AS cnt FROM edges
            WHERE source NOT IN (SELECT symbol FROM symbols)
               OR target NOT IN (SELECT symbol FROM symbols)
        """)
        edge_cnt = edge_row["cnt"] if edge_row else 0
        if edge_cnt:
            self._execute("""
                DELETE FROM edges
                WHERE source NOT IN (SELECT symbol FROM symbols)
                   OR target NOT IN (SELECT symbol FROM symbols)
            """)

        occ_row = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM occurrences WHERE symbol NOT IN (SELECT symbol FROM symbols)"
        )
        occ_cnt = occ_row["cnt"] if occ_row else 0
        if occ_cnt:
            self._execute("DELETE FROM occurrences WHERE symbol NOT IN (SELECT symbol FROM symbols)")

        return edge_cnt, occ_cnt
