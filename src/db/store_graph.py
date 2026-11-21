import logging
from typing import Dict, List, Any, Optional, Set, Iterable
from db.base import BaseRepository, UPSERT_SYMBOL_SQL, UPSERT_EDGE_SQL, normalize_path
from utils.helpers import demangle_scip_symbol

logger = logging.getLogger(__name__)


class GraphStore(BaseRepository):
    """
    Domain store owning symbols, edges, and occurrences.
    Enforces POSIX path normalization on ingress and maintains graph topology integrity.
    """

    @staticmethod
    def _format_symbol_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        res = dict(row)
        if "filepath" in res and res["filepath"]:
            res["filepath"] = normalize_path(res["filepath"])
        if not res.get("clean_symbol") and res.get("symbol"):
            res["clean_symbol"] = demangle_scip_symbol(res["symbol"])
        return res

    # ------------------ Symbols Domain ------------------

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a registered symbol declaration."""
        row = self._fetch_one(
            """SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight,
                      parent_symbol, classification, change_count, clean_symbol,
                      start_line, start_col, end_line, end_col
               FROM symbols WHERE symbol = ? OR clean_symbol = ?""",
            (symbol, symbol)
        )
        return self._format_symbol_dict(row)

    def search_symbols(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search symbols by clean_symbol or symbol substring (case-insensitive)."""
        pattern = f"%{query}%"
        rows = self._fetch_all(
            """SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight,
                      parent_symbol, classification, change_count, clean_symbol,
                      start_line, start_col, end_line, end_col
               FROM symbols WHERE LOWER(clean_symbol) LIKE LOWER(?) OR LOWER(symbol) LIKE LOWER(?) LIMIT ?""",
            (pattern, pattern, limit)
        )
        return [self._format_symbol_dict(r) for r in rows if r]

    def upsert_symbol(
        self,
        symbol: str,
        filepath: Optional[str],
        kind: str,
        signature: Optional[str] = None,
        docstring: Optional[str] = None,
        body_hash: Optional[str] = None,
        connection_weight: int = 0,
        parent_symbol: Optional[str] = None,
        clean_symbol: Optional[str] = None,
        start_line: Optional[int] = None,
        start_col: Optional[int] = None,
        end_line: Optional[int] = None,
        end_col: Optional[int] = None,
    ):
        """Inserts or updates a symbol declaration."""
        if clean_symbol is None and symbol:
            clean_symbol = demangle_scip_symbol(symbol)
        norm_fp = normalize_path(filepath)
        self._execute(
            UPSERT_SYMBOL_SQL,
            (
                symbol,
                clean_symbol,
                norm_fp,
                kind,
                signature,
                docstring,
                body_hash,
                connection_weight,
                parent_symbol,
                start_line,
                start_col,
                end_line,
                end_col,
            )
        )

    def upsert_symbols_bulk(self, symbols_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk upserts a list of symbols in a single execution."""
        if not symbols_list:
            return
        data = [
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
        self._executemany(UPSERT_SYMBOL_SQL, data)
        if progress_callback:
            progress_callback(len(data), len(data))

    def get_symbols_by_filepaths(self, filepaths: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get all symbols for a list of filepaths, returned as {symbol: {kind, body_hash, ...}}."""
        if not filepaths:
            return {}
        fps = [normalize_path(fp) for fp in filepaths]
        rows = self._fetch_all(
            """SELECT symbol, kind, body_hash, signature, docstring, filepath, parent_symbol, classification, clean_symbol,
                      start_line, start_col, end_line, end_col
               FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))""",
            (fps,)
        )
        result = {}
        for r in rows:
            res = self._format_symbol_dict(r)
            if res:
                result[res["symbol"]] = res
        return result

    def get_symbols_in_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Returns all symbols declared in a given file."""
        norm_fp = normalize_path(filepath)
        rows = self._fetch_all(
            """SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight,
                      parent_symbol, classification, change_count, clean_symbol,
                      start_line, start_col, end_line, end_col
               FROM symbols WHERE filepath = ?""",
            (norm_fp,)
        )
        return [self._format_symbol_dict(r) for r in rows if r]

    def get_symbols_metadata_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch fetch symbol metadata."""
        if not symbols:
            return {}
        rows = self._fetch_all(
            """SELECT symbol, kind, signature, docstring, filepath, parent_symbol, classification, clean_symbol,
                      start_line, start_col, end_line, end_col
               FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))""",
            (symbols,)
        )
        return {r["symbol"]: self._format_symbol_dict(r) for r in rows if r}

    def get_all_symbols(self) -> List[Dict[str, Any]]:
        """Retrieves all symbols in the workspace."""
        rows = self._fetch_all(
            """SELECT symbol, filepath, kind, signature, docstring, body_hash, connection_weight,
                      parent_symbol, classification, change_count, clean_symbol,
                      start_line, start_col, end_line, end_col
               FROM symbols"""
        )
        return [self._format_symbol_dict(r) for r in rows if r]

    def get_all_symbols_summary(self) -> List[Dict[str, Any]]:
        """Retrieves lightweight symbol summary for linking passes."""
        rows = self._fetch_all("SELECT symbol, filepath, kind, clean_symbol FROM symbols")
        for r in rows:
            if r.get("filepath"):
                r["filepath"] = normalize_path(r["filepath"])
        return rows

    def get_member_symbols(self, parent_symbol: str) -> List[Dict[str, Any]]:
        """Retrieves member methods and constructors belonging to a class symbol."""
        prefix = parent_symbol if parent_symbol.endswith("#") else parent_symbol + "#"
        return self._fetch_all(
            """SELECT symbol, kind, signature, docstring FROM symbols
               WHERE parent_symbol = ?
                  OR (symbol LIKE ? AND (kind IN ('Method', 'Constructor') OR symbol LIKE '%().'))
               ORDER BY symbol""",
            (parent_symbol, prefix + "%")
        )

    def get_existing_symbols(self, symbols: Iterable[str]) -> Set[str]:
        """Returns set of symbols that exist in database."""
        sym_list = list(symbols)
        if not sym_list:
            return set()
        rows = self._fetch_all(
            "SELECT symbol FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
            (sym_list,)
        )
        return {r["symbol"] for r in rows}

    def update_symbols_classification_bulk(self, classifications: Dict[str, Dict[str, Any]]):
        """Batch update of symbol classification JSON strings."""
        if not classifications:
            return
        import json
        data = [(json.dumps(val), sym) for sym, val in classifications.items()]
        self._executemany("UPDATE symbols SET classification = ? WHERE symbol = ?", data)

    def recalculate_connection_weights(self):
        """Recomputes connection_weight for each symbol based on incoming and outgoing edges."""
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

    def delete_symbols_bulk(self, symbols: List[str]):
        """Bulk delete symbols by ID."""
        if not symbols:
            return
        self._execute("DELETE FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))", (symbols,))

    def delete_symbols_for_files(self, filepaths: List[str]):
        """Delete symbols belonging to multiple files."""
        self._delete_by_filepaths("symbols", filepaths)

    # ------------------ Edges Domain ------------------

    def add_edge(self, source: str, target: str, relation: str, weight: float = 1.0, call_line: Optional[int] = None):
        """Inserts or updates a single edge relation."""
        self._execute(UPSERT_EDGE_SQL, (source, target, relation, weight, call_line))

    def add_edges_bulk(self, edges_list: List[Dict[str, Any]]):
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
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Queries edges matching optional source, target, and relation filters."""
        query = "SELECT source, target, relation, weight, call_line FROM edges WHERE 1=1"
        params: List[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if target:
            query += " AND target = ?"
            params.append(target)
        if relation:
            query += " AND relation = ?"
            params.append(relation)
        return self._fetch_all(query, params)

    def get_edges_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns all incoming and outgoing edges for a symbol."""
        return self._fetch_all(
            "SELECT source, target, relation, weight, call_line FROM edges WHERE source = ? OR target = ?",
            (symbol, symbol)
        )

    def get_outgoing_edges(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns direct outgoing edges from symbol."""
        return self._fetch_all(
            "SELECT target, relation, weight, call_line FROM edges WHERE source = ?",
            (symbol,)
        )

    def get_incoming_edges(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns direct incoming edges to symbol."""
        return self._fetch_all(
            "SELECT source, relation, weight, call_line FROM edges WHERE target = ?",
            (symbol,)
        )

    def get_edges_by_targets(self, targets: List[str]) -> List[Dict[str, Any]]:
        """Returns incoming edges to any of the target symbols."""
        if not targets:
            return []
        return self._fetch_all(
            "SELECT source, target, relation, weight, call_line FROM edges WHERE target IN (SELECT UNNEST(?::VARCHAR[]))",
            (targets,)
        )

    def get_all_edges(self) -> List[Dict[str, Any]]:
        """Returns all edges including relation and call_line."""
        return self._fetch_all("SELECT source, target, relation, weight, call_line FROM edges")

    def get_edges_with_locations(self) -> List[Dict[str, Any]]:
        """Returns edges with call line locations joined from occurrences/call_line."""
        return self._fetch_all(
            """
            SELECT e.source, e.target, e.relation, e.weight,
                   COALESCE(e.call_line, o.start_line) AS line, o.start_col AS col
            FROM edges e
            LEFT JOIN symbols s ON e.source = s.symbol
            LEFT JOIN occurrences o ON e.target = o.symbol AND s.filepath = o.filepath
            """
        )

    def update_edge_weights_bulk(self, weight_updates: List[tuple]):
        """Batch update edge weights: list of (weight, source, target, relation)."""
        if not weight_updates:
            return
        self._executemany(
            "UPDATE edges SET weight = ? WHERE source = ? AND target = ? AND relation = ?",
            weight_updates
        )

    def delete_edges_by_relation(self, relation: str):
        """Deletes edges of a specific relation."""
        self._execute("DELETE FROM edges WHERE relation = ?", (relation,))

    def delete_edges_for_files(self, filepaths: List[str]):
        """Delete all edges linking to symbols in multiple files."""
        if not filepaths:
            return
        fps = [normalize_path(fp) for fp in filepaths]
        self._execute(
            """DELETE FROM edges
               WHERE source IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))
                  OR target IN (SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[])))""",
            (fps, fps)
        )

    def delete_orphaned_edges(self) -> int:
        """Deletes edges where source or target symbol no longer exists."""
        row = self._fetch_one("""
            SELECT COUNT(*) AS cnt FROM edges
            WHERE source NOT IN (SELECT symbol FROM symbols)
               OR target NOT IN (SELECT symbol FROM symbols)
        """)
        cnt = row["cnt"] if row else 0
        self._execute("""
            DELETE FROM edges
            WHERE source NOT IN (SELECT symbol FROM symbols)
               OR target NOT IN (SELECT symbol FROM symbols)
        """)
        return cnt

    def get_dependent_files(self, filepaths: List[str]) -> List[str]:
        """Finds files containing symbols that depend on the given files."""
        if not filepaths:
            return []
        fps = [normalize_path(fp) for fp in filepaths]
        rows = self._fetch_all(
            """SELECT DISTINCT s_src.filepath
               FROM edges e
               JOIN symbols s_src ON e.source = s_src.symbol
               JOIN symbols s_tgt ON e.target = s_tgt.symbol
               WHERE s_tgt.filepath IN (SELECT UNNEST(?::VARCHAR[]))
                 AND s_src.filepath NOT IN (SELECT UNNEST(?::VARCHAR[]))
                 AND s_src.filepath IS NOT NULL""",
            (fps, fps)
        )
        return [normalize_path(r["filepath"]) for r in rows if r.get("filepath")]

    # ------------------ Occurrences Domain ------------------

    def record_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]], progress_callback=None):
        """Bulk inserts occurrences."""
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
            data
        )
        if progress_callback:
            progress_callback(len(data), len(data))

    def add_occurrence(
        self,
        symbol: str,
        filepath: str,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
        role: int
    ):
        """Inserts an occurrence."""
        self._execute(
            "INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, normalize_path(filepath), start_line, start_col, end_line, end_col, role)
        )

    def get_occurrences_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Returns all occurrences for a symbol."""
        rows = self._fetch_all(
            "SELECT symbol, filepath, start_line, start_col, end_line, end_col, role FROM occurrences WHERE symbol = ?",
            (symbol,)
        )
        for r in rows:
            r["filepath"] = normalize_path(r["filepath"])
        return rows

    def get_occurrences_for_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Returns all occurrences located in a file."""
        norm_fp = normalize_path(filepath)
        rows = self._fetch_all(
            "SELECT symbol, filepath, start_line, start_col, end_line, end_col, role FROM occurrences WHERE filepath = ?",
            (norm_fp,)
        )
        for r in rows:
            r["filepath"] = normalize_path(r["filepath"])
        return rows

    def get_occurrences_filtered(
        self,
        filepath_filter: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetches occurrences matching optional filepath filter."""
        query = "SELECT symbol, filepath, start_line, start_col, end_line, end_col, role FROM occurrences"
        params: List[Any] = []
        if filepath_filter:
            query += " WHERE filepath LIKE ?"
            params.append(f"%{normalize_path(filepath_filter)}%")
        query += " ORDER BY filepath, start_line, start_col"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = self._fetch_all(query, params)
        for r in rows:
            r["filepath"] = normalize_path(r.get("filepath"))
        return rows

    def get_definitions_map(self) -> Dict[str, Dict[str, Any]]:
        """Fetches symbol definitions from symbols table and definition occurrences."""
        rows = self._fetch_all(
            """SELECT symbol, filepath, start_line, start_col, end_line, end_col
               FROM symbols WHERE start_line IS NOT NULL
               UNION
               SELECT symbol, filepath, start_line, start_col, end_line, end_col
               FROM occurrences WHERE (role & 1) != 0"""
        )
        defs = {}
        for r in rows:
            sym = r["symbol"]
            if sym not in defs:
                defs[sym] = {
                    "symbol": sym,
                    "filepath": normalize_path(r["filepath"]),
                    "start_line": int(r["start_line"]) if r.get("start_line") is not None else 0,
                    "start_col": int(r["start_col"]) if r.get("start_col") is not None else 0,
                    "end_line": int(r["end_line"]) if r.get("end_line") is not None else 0,
                    "end_col": int(r["end_col"]) if r.get("end_col") is not None else 0,
                }
        return defs

    def delete_occurrences_for_files(self, filepaths: List[str]):
        """Delete occurrences in multiple files."""
        self._delete_by_filepaths("occurrences", filepaths)

    def delete_orphaned_occurrences(self) -> int:
        """Deletes occurrences whose symbol no longer exists in symbols table."""
        row = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM occurrences WHERE symbol NOT IN (SELECT symbol FROM symbols)"
        )
        cnt = row["cnt"] if row else 0
        self._execute(
            "DELETE FROM occurrences WHERE symbol NOT IN (SELECT symbol FROM symbols)"
        )
        return cnt
