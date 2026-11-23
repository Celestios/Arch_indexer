import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from db.base import (
    BaseRepository,
    UPSERT_SYNTACTIC_SYMBOL_SQL,
    UPSERT_SYNTACTIC_SYMBOLS_VECTORIZED_SQL,
    UPSERT_SEMANTIC_SYMBOL_SQL,
    UPSERT_SEMANTIC_SYMBOLS_VECTORIZED_SQL,
    UPSERT_EDGE_SQL,
    UPSERT_EDGES_VECTORIZED_SQL,
    UPSERT_OCCURRENCES_VECTORIZED_SQL,
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
    def _build_symbol_columns(symbols_list: List[Dict[str, Any]]) -> tuple:
        syms, cleans, fps, kinds = [], [], [], []
        sigs, docs, hashes, weights = [], [], [], []
        parents, sl, sc, el, ec = [], [], [], [], []
        for sym in symbols_list:
            syms.append(sym["symbol"])
            cleans.append(sym.get("clean_symbol") or demangle_scip_symbol(sym["symbol"]))
            fps.append(normalize_path(sym.get("filepath")) if sym.get("filepath") else None)
            kinds.append(sym["kind"])
            sigs.append(sym.get("signature"))
            docs.append(sym.get("docstring"))
            hashes.append(sym.get("body_hash"))
            weights.append(int(sym.get("connection_weight", 0)))
            parents.append(sym.get("parent_symbol"))
            sl.append(sym.get("start_line"))
            sc.append(sym.get("start_col"))
            el.append(sym.get("end_line"))
            ec.append(sym.get("end_col"))
        return (syms, cleans, fps, kinds, sigs, docs, hashes, weights, parents, sl, sc, el, ec)

    # ------------------ Symbols Domain ------------------

    def upsert_syntactic_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Tier-1 (Tree-sitter) bulk upsert owning syntactic columns and declaration coordinates."""
        if not symbols_list:
            return
        headers = [
            'symbol', 'clean_symbol', 'filepath', 'kind', 'signature', 'docstring',
            'body_hash', 'connection_weight', 'parent_symbol', 'start_line', 'start_col', 'end_line', 'end_col'
        ]
        rows = [
            [
                s["symbol"],
                s.get("clean_symbol") or demangle_scip_symbol(s["symbol"]),
                normalize_path(s.get("filepath")) if s.get("filepath") else None,
                s["kind"],
                s.get("signature") or "",
                s.get("docstring") or "",
                s.get("body_hash") or "",
                int(s.get("connection_weight", 0)),
                s.get("parent_symbol"),
                s.get("start_line"),
                s.get("start_col"),
                s.get("end_line"),
                s.get("end_col"),
            ]
            for s in symbols_list
        ]
        with self._csv_staging(headers, rows) as csv_path:
            with self._db_conn.session() as conn:
                conn.execute("""
                    CREATE TEMP TABLE IF NOT EXISTS _stg_syn_symbols (
                        symbol VARCHAR, clean_symbol VARCHAR, filepath VARCHAR, kind VARCHAR,
                        signature TEXT, docstring TEXT, body_hash VARCHAR, connection_weight INTEGER,
                        parent_symbol VARCHAR, start_line INTEGER, start_col INTEGER, end_line INTEGER, end_col INTEGER
                    )
                """)
                conn.execute("DELETE FROM _stg_syn_symbols")
                conn.execute(f"""
                    INSERT INTO _stg_syn_symbols SELECT * FROM read_csv(
                        '{csv_path}',
                        header=true,
                        delim=',',
                        quote='"',
                        escape='"',
                        nullstr='',
                        columns={{
                            'symbol': 'VARCHAR',
                            'clean_symbol': 'VARCHAR',
                            'filepath': 'VARCHAR',
                            'kind': 'VARCHAR',
                            'signature': 'VARCHAR',
                            'docstring': 'VARCHAR',
                            'body_hash': 'VARCHAR',
                            'connection_weight': 'INTEGER',
                            'parent_symbol': 'VARCHAR',
                            'start_line': 'INTEGER',
                            'start_col': 'INTEGER',
                            'end_line': 'INTEGER',
                            'end_col': 'INTEGER'
                        }}
                    )
                """)

                conn.execute("""
                    UPDATE symbols
                    SET clean_symbol = COALESCE(NULLIF(stg.clean_symbol, ''), symbols.clean_symbol),
                        filepath = COALESCE(stg.filepath, symbols.filepath),
                        kind = CASE WHEN stg.kind IS NOT NULL AND stg.kind <> 'UnspecifiedKind' THEN stg.kind ELSE symbols.kind END,
                        signature = CASE WHEN stg.signature IS NOT NULL AND stg.signature <> '' THEN stg.signature ELSE symbols.signature END,
                        docstring = CASE WHEN stg.docstring IS NOT NULL AND stg.docstring <> '' THEN stg.docstring ELSE symbols.docstring END,
                        change_count = CASE WHEN symbols.body_hash IS NOT NULL AND stg.body_hash IS NOT NULL AND symbols.body_hash <> stg.body_hash THEN COALESCE(symbols.change_count, 1) + 1 ELSE COALESCE(symbols.change_count, 1) END,
                        last_modified = CASE WHEN symbols.body_hash IS NOT NULL AND stg.body_hash IS NOT NULL AND symbols.body_hash <> stg.body_hash THEN now() ELSE symbols.last_modified END,
                        body_hash = COALESCE(stg.body_hash, symbols.body_hash),
                        parent_symbol = COALESCE(stg.parent_symbol, symbols.parent_symbol),
                        start_line = COALESCE(stg.start_line, symbols.start_line),
                        start_col = COALESCE(stg.start_col, symbols.start_col),
                        end_line = COALESCE(stg.end_line, symbols.end_line),
                        end_col = COALESCE(stg.end_col, symbols.end_col)
                    FROM _stg_syn_symbols stg
                    WHERE symbols.symbol = stg.symbol
                """)

                conn.execute("""
                    INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
                    SELECT DISTINCT ON (symbol)
                        symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col
                    FROM _stg_syn_symbols stg
                    WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.symbol = stg.symbol)
                """)
                conn.execute("DROP TABLE IF EXISTS _stg_syn_symbols")

    def upsert_semantic_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Tier-2 (SCIP) bulk upsert preserving Tier-1 syntactic columns and populating SCIP-only symbols."""
        if not symbols_list:
            return
        headers = [
            'symbol', 'clean_symbol', 'filepath', 'kind', 'signature', 'docstring',
            'body_hash', 'connection_weight', 'parent_symbol', 'start_line', 'start_col', 'end_line', 'end_col'
        ]
        rows = [
            [
                s["symbol"],
                s.get("clean_symbol") or demangle_scip_symbol(s["symbol"]),
                normalize_path(s.get("filepath")) if s.get("filepath") else None,
                s.get("kind", "Unknown"),
                s.get("signature") or "",
                s.get("docstring") or "",
                s.get("body_hash") or "",
                int(s.get("connection_weight", 0)),
                s.get("parent_symbol"),
                s.get("start_line"),
                s.get("start_col"),
                s.get("end_line"),
                s.get("end_col"),
            ]
            for s in symbols_list
        ]
        with self._csv_staging(headers, rows) as csv_path:
            with self._db_conn.session() as conn:
                conn.execute("""
                    CREATE TEMP TABLE IF NOT EXISTS _stg_sem_symbols (
                        symbol VARCHAR, clean_symbol VARCHAR, filepath VARCHAR, kind VARCHAR,
                        signature TEXT, docstring TEXT, body_hash VARCHAR, connection_weight INTEGER,
                        parent_symbol VARCHAR, start_line INTEGER, start_col INTEGER, end_line INTEGER, end_col INTEGER
                    )
                """)
                conn.execute("DELETE FROM _stg_sem_symbols")
                conn.execute(f"""
                    INSERT INTO _stg_sem_symbols SELECT * FROM read_csv(
                        '{csv_path}',
                        header=true,
                        delim=',',
                        quote='"',
                        escape='"',
                        nullstr='',
                        columns={{
                            'symbol': 'VARCHAR',
                            'clean_symbol': 'VARCHAR',
                            'filepath': 'VARCHAR',
                            'kind': 'VARCHAR',
                            'signature': 'VARCHAR',
                            'docstring': 'VARCHAR',
                            'body_hash': 'VARCHAR',
                            'connection_weight': 'INTEGER',
                            'parent_symbol': 'VARCHAR',
                            'start_line': 'INTEGER',
                            'start_col': 'INTEGER',
                            'end_line': 'INTEGER',
                            'end_col': 'INTEGER'
                        }}
                    )
                """)

                conn.execute("""
                    UPDATE symbols
                    SET clean_symbol = COALESCE(NULLIF(symbols.clean_symbol, ''), stg.clean_symbol),
                        filepath = COALESCE(symbols.filepath, stg.filepath),
                        kind = CASE WHEN symbols.kind IS NOT NULL AND symbols.kind <> 'UnspecifiedKind' THEN symbols.kind ELSE stg.kind END,
                        signature = CASE WHEN symbols.signature IS NOT NULL AND symbols.signature <> '' THEN symbols.signature ELSE stg.signature END,
                        docstring = CASE WHEN symbols.docstring IS NOT NULL AND symbols.docstring <> '' THEN symbols.docstring ELSE stg.docstring END,
                        body_hash = COALESCE(symbols.body_hash, stg.body_hash),
                        parent_symbol = COALESCE(symbols.parent_symbol, stg.parent_symbol),
                        start_line = COALESCE(symbols.start_line, stg.start_line),
                        start_col = COALESCE(symbols.start_col, stg.start_col),
                        end_line = COALESCE(symbols.end_line, stg.end_line),
                        end_col = COALESCE(symbols.end_col, stg.end_col)
                    FROM _stg_sem_symbols stg
                    WHERE symbols.symbol = stg.symbol
                """)

                conn.execute("""
                    INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
                    SELECT DISTINCT ON (symbol)
                        symbol, clean_symbol, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col
                    FROM _stg_sem_symbols stg
                    WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.symbol = stg.symbol)
                """)
                conn.execute("DROP TABLE IF EXISTS _stg_sem_symbols")

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
        """Vectorized batch update of symbol classification JSON strings."""
        if not classifications:
            return
        syms = list(classifications.keys())
        classes = [json.dumps(classifications[s]) for s in syms]
        self._execute(
            """UPDATE symbols
               SET classification = u.c
               FROM (
                   SELECT UNNEST(?::VARCHAR[]) AS c,
                          UNNEST(?::VARCHAR[]) AS s
               ) u
               WHERE symbols.symbol = u.s""",
            (classes, syms),
        )

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
        """Bulk upsert of edges via CSV staging and set-based update/insert."""
        if not edges_list:
            return
        headers = ['source', 'target', 'relation', 'weight', 'call_line']
        rows = [
            [
                e["source"],
                e["target"],
                e.get("relation", "Calls"),
                float(e.get("weight", 1.0)),
                e.get("call_line") or e.get("line"),
            ]
            for e in edges_list
        ]
        with self._csv_staging(headers, rows) as csv_path:
            with self._db_conn.session() as conn:
                conn.execute("""
                    CREATE TEMP TABLE IF NOT EXISTS _stg_edges (
                        source VARCHAR, target VARCHAR, relation VARCHAR, weight FLOAT, call_line INTEGER
                    )
                """)
                conn.execute("DELETE FROM _stg_edges")
                conn.execute(f"""
                    INSERT INTO _stg_edges SELECT * FROM read_csv(
                        '{csv_path}',
                        header=true,
                        delim=',',
                        quote='"',
                        escape='"',
                        nullstr='',
                        columns={{
                            'source': 'VARCHAR',
                            'target': 'VARCHAR',
                            'relation': 'VARCHAR',
                            'weight': 'DOUBLE',
                            'call_line': 'INTEGER'
                        }}
                    )
                """)

                conn.execute("""
                    UPDATE edges
                    SET weight = stg.weight,
                        call_line = COALESCE(stg.call_line, edges.call_line)
                    FROM (
                        SELECT DISTINCT ON (source, target, relation) source, target, relation, weight, call_line
                        FROM _stg_edges
                    ) stg
                    WHERE edges.source = stg.source AND edges.target = stg.target AND edges.relation = stg.relation
                """)

                conn.execute("""
                    INSERT INTO edges (source, target, relation, weight, call_line)
                    SELECT DISTINCT ON (source, target, relation) source, target, relation, weight, call_line
                    FROM _stg_edges stg
                    WHERE NOT EXISTS (
                        SELECT 1 FROM edges e
                        WHERE e.source = stg.source AND e.target = stg.target AND e.relation = stg.relation
                    )
                """)
                conn.execute("DROP TABLE IF EXISTS _stg_edges")

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
        """Vectorized batch update of edge weights."""
        if not weight_updates:
            return
        weights = [float(u[0]) for u in weight_updates]
        sources = [u[1] for u in weight_updates]
        targets = [u[2] for u in weight_updates]
        relations = [u[3] for u in weight_updates]
        self._execute(
            """UPDATE edges
               SET weight = u.w
               FROM (
                   SELECT UNNEST(?::DOUBLE[]) AS w,
                          UNNEST(?::VARCHAR[]) AS s,
                          UNNEST(?::VARCHAR[]) AS t,
                          UNNEST(?::VARCHAR[]) AS r
               ) u
               WHERE edges.source = u.s AND edges.target = u.t AND edges.relation = u.r""",
            (weights, sources, targets, relations),
        )

    def remap_edge_symbols(self, id_map: Dict[str, str]):
        """Remaps edge source and target symbols when Tier-1 IDs are upgraded to Tier-2 IDs."""
        if not id_map:
            return
        old_ids = list(id_map.keys())
        new_ids = list(id_map.values())
        self._execute("""
            UPDATE edges
            SET source = u.new_id
            FROM (SELECT UNNEST(?::VARCHAR[]) AS old_id, UNNEST(?::VARCHAR[]) AS new_id) u
            WHERE edges.source = u.old_id
        """, (old_ids, new_ids))
        self._execute("""
            UPDATE edges
            SET target = u.new_id
            FROM (SELECT UNNEST(?::VARCHAR[]) AS old_id, UNNEST(?::VARCHAR[]) AS new_id) u
            WHERE edges.target = u.old_id
        """, (old_ids, new_ids))

    def delete_edges(
        self,
        relation: Optional[str] = None,
        filepaths: Optional[List[str]] = None,
        exclude_relations: Optional[List[str]] = None,
    ):
        """Deletes edges matching a relation type and/or touching symbols in filepaths via linear semi-joins."""
        if relation:
            self._execute("DELETE FROM edges WHERE relation = ?", (relation,))
        if filepaths:
            fps = [normalize_path(fp) for fp in filepaths if fp]
            if fps:
                # Materialize target symbols into an unindexed temp table for linear hash semi-joins
                self._execute(
                    "CREATE TEMP TABLE IF NOT EXISTS _stg_del_syms AS SELECT symbol FROM symbols WHERE filepath IN (SELECT UNNEST(?::VARCHAR[]))",
                    (fps,),
                )
                if exclude_relations:
                    self._execute(
                        """DELETE FROM edges
                           WHERE source IN (SELECT symbol FROM _stg_del_syms)
                             AND relation NOT IN (SELECT UNNEST(?::VARCHAR[]))""",
                        (exclude_relations,),
                    )
                    self._execute(
                        """DELETE FROM edges
                           WHERE target IN (SELECT symbol FROM _stg_del_syms)
                             AND relation NOT IN (SELECT UNNEST(?::VARCHAR[]))""",
                        (exclude_relations,),
                    )
                else:
                    self._execute("DELETE FROM edges WHERE source IN (SELECT symbol FROM _stg_del_syms)")
                    self._execute("DELETE FROM edges WHERE target IN (SELECT symbol FROM _stg_del_syms)")
                self._execute("DROP TABLE IF EXISTS _stg_del_syms")

    # ------------------ Occurrences & Hygiene Domain ------------------

    def upsert_occurrences(self, occurrences_list: List[Dict[str, Any]]):
        """Bulk insert of reference occurrences via CSV staging and direct append."""
        if not occurrences_list:
            return
        headers = ['symbol', 'filepath', 'start_line', 'start_col', 'end_line', 'end_col', 'role']
        rows = [
            [
                occ["symbol"],
                normalize_path(occ["filepath"]),
                int(occ["start_line"]),
                int(occ["start_col"]),
                int(occ["end_line"]),
                int(occ["end_col"]),
                int(occ["role"]),
            ]
            for occ in occurrences_list
        ]
        with self._csv_staging(headers, rows) as csv_path:
            with self._db_conn.session() as conn:
                conn.execute(f"""
                    INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
                    SELECT symbol, filepath, start_line, start_col, end_line, end_col, role
                    FROM read_csv(
                        '{csv_path}',
                        header=true,
                        delim=',',
                        quote='"',
                        escape='"',
                        nullstr='',
                        columns={{
                            'symbol': 'VARCHAR',
                            'filepath': 'VARCHAR',
                            'start_line': 'INTEGER',
                            'start_col': 'INTEGER',
                            'end_line': 'INTEGER',
                            'end_col': 'INTEGER',
                            'role': 'INTEGER'
                        }}
                    )
                """)

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
        """Deletes edges and occurrences whose symbols no longer exist via linear anti-joins. Returns (edges_deleted, occs_deleted)."""
        row1 = self._fetch_one("SELECT COUNT(*) AS cnt FROM edges WHERE source NOT IN (SELECT symbol FROM symbols)")
        row2 = self._fetch_one("SELECT COUNT(*) AS cnt FROM edges WHERE target NOT IN (SELECT symbol FROM symbols)")
        edge_cnt = (row1["cnt"] if row1 else 0) + (row2["cnt"] if row2 else 0)
        if edge_cnt:
            self._execute("DELETE FROM edges WHERE source NOT IN (SELECT symbol FROM symbols)")
            self._execute("DELETE FROM edges WHERE target NOT IN (SELECT symbol FROM symbols)")

        occ_row = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM occurrences WHERE symbol NOT IN (SELECT symbol FROM symbols)"
        )
        occ_cnt = occ_row["cnt"] if occ_row else 0
        if occ_cnt:
            self._execute("DELETE FROM occurrences WHERE symbol NOT IN (SELECT symbol FROM symbols)")

        return edge_cnt, occ_cnt
