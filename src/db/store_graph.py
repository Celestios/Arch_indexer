import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from db.base import BaseRepository, normalize_path
from utils.helpers import is_auxiliary_path
from utils.symbol_id import canonical_display_name, parse_canonical_id

logger = logging.getLogger(__name__)

_SYMBOL_COLS = """
    symbol, name, scip_id, filepath, kind, signature, docstring, body_hash, connection_weight,
    parent_symbol, classification, change_count,
    start_line, start_col, end_line, end_col
"""

_SYMBOL_STAGING_HEADERS = [
    "symbol",
    "name",
    "scip_id",
    "filepath",
    "kind",
    "signature",
    "docstring",
    "body_hash",
    "connection_weight",
    "parent_symbol",
    "start_line",
    "start_col",
    "end_line",
    "end_col",
]


class GraphStore(BaseRepository):
    """
    Domain store owning canonical symbols, edges, and reference occurrences.
    Enforces POSIX path normalization on ingress and disjoint Tier-1/Tier-2 symbol upserts.
    """

    @staticmethod
    def _format_symbol_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        res = dict(row)
        if res.get("filepath"):
            res["filepath"] = normalize_path(res["filepath"])
        if not res.get("name") and res.get("symbol"):
            res["name"] = parse_canonical_id(res["symbol"])[2] or res["symbol"]
        return res

    @contextmanager
    def _stage_symbols(self, temp_table: str, symbols_list: List[Dict[str, Any]]):
        """Shared CSV staging pipeline for Tier-1 syntactic and Tier-2 semantic symbol upserts."""
        rows = [
            [
                s["symbol"],
                s.get("name") or parse_canonical_id(s["symbol"])[2] or s["symbol"],
                s.get("scip_id"),
                normalize_path(s.get("filepath")) if s.get("filepath") else None,
                s.get("kind", "UnspecifiedKind"),
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
        with self._csv_staging(_SYMBOL_STAGING_HEADERS, rows) as csv_path:
            with self._db_conn.session() as conn:
                conn.execute(
                    f"""
                    CREATE TEMP TABLE IF NOT EXISTS {temp_table} (
                        symbol VARCHAR, name VARCHAR, scip_id VARCHAR, filepath VARCHAR, kind VARCHAR,
                        signature TEXT, docstring TEXT, body_hash VARCHAR, connection_weight INTEGER,
                        parent_symbol VARCHAR, start_line INTEGER, start_col INTEGER, end_line INTEGER, end_col INTEGER
                    )
                    """
                )
                conn.execute(f"DELETE FROM {temp_table}")
                conn.execute(
                    f"""
                    INSERT INTO {temp_table} SELECT * FROM read_csv(
                        '{csv_path}',
                        header=true,
                        delim=',',
                        quote='"',
                        escape='"',
                        nullstr='',
                        columns={{
                            'symbol': 'VARCHAR',
                            'name': 'VARCHAR',
                            'scip_id': 'VARCHAR',
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
                    """
                )
                try:
                    yield conn
                finally:
                    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")

    # ------------------ Symbols Domain ------------------

    def upsert_syntactic_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Tier-1 (Tree-sitter) bulk upsert owning syntactic columns and declaration coordinates."""
        if not symbols_list:
            return
        with self._stage_symbols("_stg_syn_symbols", symbols_list) as conn:
            conn.execute(
                """
                UPDATE symbols
                SET name = COALESCE(NULLIF(stg.name, ''), symbols.name),
                    scip_id = COALESCE(stg.scip_id, symbols.scip_id),
                    filepath = COALESCE(stg.filepath, symbols.filepath),
                    kind = CASE WHEN stg.kind IS NOT NULL AND stg.kind <> 'UnspecifiedKind' THEN stg.kind ELSE symbols.kind END,
                    signature = CASE WHEN stg.signature IS NOT NULL AND stg.signature <> '' THEN stg.signature ELSE symbols.signature END,
                    docstring = CASE WHEN stg.docstring IS NOT NULL AND stg.docstring <> '' THEN stg.docstring ELSE symbols.docstring END,
                    change_count = CASE
                        WHEN symbols.body_hash IS NOT NULL AND stg.body_hash IS NOT NULL AND symbols.body_hash <> stg.body_hash
                        THEN COALESCE(symbols.change_count, 1) + 1
                        ELSE COALESCE(symbols.change_count, 1)
                    END,
                    last_modified = CASE
                        WHEN symbols.body_hash IS NOT NULL AND stg.body_hash IS NOT NULL AND symbols.body_hash <> stg.body_hash
                        THEN now()
                        ELSE symbols.last_modified
                    END,
                    body_hash = COALESCE(stg.body_hash, symbols.body_hash),
                    parent_symbol = COALESCE(NULLIF(stg.parent_symbol, ''), symbols.parent_symbol),
                    start_line = COALESCE(stg.start_line, symbols.start_line),
                    start_col = COALESCE(stg.start_col, symbols.start_col),
                    end_line = COALESCE(stg.end_line, symbols.end_line),
                    end_col = COALESCE(stg.end_col, symbols.end_col)
                FROM _stg_syn_symbols stg
                WHERE symbols.symbol = stg.symbol
                """
            )
            conn.execute(
                """
                INSERT INTO symbols (symbol, name, scip_id, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
                SELECT DISTINCT ON (symbol)
                    symbol, name, scip_id, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col
                FROM _stg_syn_symbols stg
                WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.symbol = stg.symbol)
                """
            )

    def upsert_semantic_symbols(self, symbols_list: List[Dict[str, Any]]):
        """Tier-2 (SCIP) bulk upsert owning semantic identity (scip_id, canonical parent_symbol) and filling absent syntactic fields."""
        if not symbols_list:
            return
        with self._stage_symbols("_stg_sem_symbols", symbols_list) as conn:
            conn.execute(
                """
                UPDATE symbols
                SET name = COALESCE(NULLIF(stg.name, ''), symbols.name),
                    scip_id = COALESCE(stg.scip_id, symbols.scip_id),
                    filepath = COALESCE(symbols.filepath, stg.filepath),
                    kind = CASE WHEN symbols.kind IS NOT NULL AND symbols.kind <> 'UnspecifiedKind' THEN symbols.kind ELSE stg.kind END,
                    signature = CASE WHEN symbols.signature IS NOT NULL AND symbols.signature <> '' THEN symbols.signature ELSE stg.signature END,
                    docstring = CASE WHEN symbols.docstring IS NOT NULL AND symbols.docstring <> '' THEN symbols.docstring ELSE stg.docstring END,
                    body_hash = COALESCE(symbols.body_hash, stg.body_hash),
                    parent_symbol = COALESCE(NULLIF(stg.parent_symbol, ''), symbols.parent_symbol),
                    start_line = COALESCE(symbols.start_line, stg.start_line),
                    start_col = COALESCE(symbols.start_col, stg.start_col),
                    end_line = COALESCE(symbols.end_line, stg.end_line),
                    end_col = COALESCE(symbols.end_col, stg.end_col)
                FROM _stg_sem_symbols stg
                WHERE symbols.symbol = stg.symbol
                """
            )
            conn.execute(
                """
                INSERT INTO symbols (symbol, name, scip_id, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col)
                SELECT DISTINCT ON (symbol)
                    symbol, name, scip_id, filepath, kind, signature, docstring, body_hash, connection_weight, parent_symbol, start_line, start_col, end_line, end_col
                FROM _stg_sem_symbols stg
                WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.symbol = stg.symbol)
                """
            )

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves a registered symbol declaration by exact canonical primary key."""
        row = self._fetch_one(
            """
            SELECT s.symbol, s.name, s.scip_id, s.filepath, s.kind, s.signature, s.docstring, s.body_hash, s.connection_weight,
                   s.parent_symbol, s.classification, s.change_count,
                   COALESCE(s.start_line, o.start_line) AS start_line,
                   COALESCE(s.start_col, o.start_col) AS start_col,
                   COALESCE(s.end_line, o.end_line) AS end_line,
                   COALESCE(s.end_col, o.end_col) AS end_col
            FROM symbols s
            LEFT JOIN (
                SELECT symbol, start_line, start_col, end_line, end_col
                FROM occurrences
                WHERE (role & 1) = 1
                QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY start_line ASC) = 1
            ) o ON s.symbol = o.symbol
            WHERE s.symbol = ?
            """,
            (symbol,),
        )
        return self._format_symbol_dict(row)

    def resolve_symbol(self, target: str) -> Optional[Dict[str, Any]]:
        """Resolves a canonical ID, qualified scope::name, or leaf name to a single symbol dict."""
        target_clean = target.strip()
        if not target_clean:
            return None

        exact = self.get_symbol(target_clean)
        if exact:
            return exact

        t = target_clean[:-2] if target_clean.endswith("()") else target_clean
        patterns = [t]
        if "::" in t:
            parts = [p for p in t.split("::") if p]
            if parts:
                patterns.append(parts[-1])
        elif "." in t:
            parts = [p for p in t.split(".") if p]
            if parts:
                patterns.append(parts[-1])

        for pattern in patterns:
            raw_cands = self.search_symbols(pattern, limit=50)
            candidates = [
                s for s in raw_cands
                if not s["symbol"].startswith("local ")
                and s.get("kind") != "Parameter"
            ]
            if candidates:
                def _score(s: Dict[str, Any]) -> Tuple[int, int, int, str]:
                    sid = s["symbol"]
                    leaf = s.get("name") or parse_canonical_id(sid)[2]
                    disp = canonical_display_name(sid, leaf)
                    is_aux = is_auxiliary_path(s.get("filepath"))
                    is_exact = (
                        sid == target_clean
                        or disp == t
                        or leaf == t
                        or leaf == pattern
                        or sid.endswith("::" + t)
                    )
                    return (0 if is_exact else 1, 1 if is_aux else 0, len(sid), sid)

                candidates.sort(key=_score)
                return candidates[0]

        return None

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
        """Batch-fetches symbol records keyed by canonical symbol ID."""
        if not symbols:
            return {}
        rows = self._fetch_all(
            """
            SELECT s.symbol, s.name, s.scip_id, s.filepath, s.kind, s.signature, s.docstring, s.body_hash, s.connection_weight,
                   s.parent_symbol, s.classification, s.change_count,
                   COALESCE(s.start_line, o.start_line) AS start_line,
                   COALESCE(s.start_col, o.start_col) AS start_col,
                   COALESCE(s.end_line, o.end_line) AS end_line,
                   COALESCE(s.end_col, o.end_col) AS end_col
            FROM symbols s
            LEFT JOIN (
                SELECT symbol, start_line, start_col, end_line, end_col
                FROM occurrences
                WHERE (role & 1) = 1
                QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY start_line ASC) = 1
            ) o ON s.symbol = o.symbol
            WHERE s.symbol IN (SELECT UNNEST(?::VARCHAR[]))
            """,
            (list(symbols),),
        )
        return {r["symbol"]: self._format_symbol_dict(r) for r in rows if r}

    def get_all_symbols(self) -> List[Dict[str, Any]]:
        """Retrieves all symbols in the workspace."""
        rows = self._fetch_all(f"SELECT {_SYMBOL_COLS} FROM symbols")
        return [self._format_symbol_dict(r) for r in rows if r]

    def get_scip_id_map(self) -> Dict[str, str]:
        """Returns mapping of {scip_id: symbol} for all indexed rows with non-null scip_id."""
        rows = self._fetch_all("SELECT scip_id, symbol FROM symbols WHERE scip_id IS NOT NULL")
        return {r["scip_id"]: r["symbol"] for r in rows if r.get("scip_id")}

    def get_member_symbols(self, parent_symbol: str) -> List[Dict[str, Any]]:
        """Retrieves member methods, fields, and constructors belonging to a canonical parent symbol."""
        prefix = parent_symbol + "::"
        return self._fetch_all(
            """SELECT symbol, name, kind, signature, docstring FROM symbols
               WHERE parent_symbol = ? OR starts_with(symbol, ?)
               ORDER BY symbol""",
            (parent_symbol, prefix),
        )

    def search_symbols(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Case-insensitive substring search over name and canonical symbol ID."""
        pattern = f"%{query}%"
        rows = self._fetch_all(
            f"""SELECT {_SYMBOL_COLS} FROM symbols
                WHERE LOWER(name) LIKE LOWER(?) OR LOWER(symbol) LIKE LOWER(?)
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
        self._execute(
            """
            UPDATE symbols
            SET connection_weight = COALESCE(e_in.cnt, 0) + COALESCE(e_out.cnt, 0)
            FROM (
                SELECT target AS sym, COUNT(*) AS cnt FROM edges GROUP BY target
            ) e_in FULL OUTER JOIN (
                SELECT source AS sym, COUNT(*) AS cnt FROM edges GROUP BY source
            ) e_out ON e_in.sym = e_out.sym
            WHERE symbols.symbol = COALESCE(e_in.sym, e_out.sym)
            """
        )

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
        headers = ["source", "target", "relation", "weight", "call_line"]
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
                conn.execute(
                    """
                    CREATE TEMP TABLE IF NOT EXISTS _stg_edges (
                        source VARCHAR, target VARCHAR, relation VARCHAR, weight FLOAT, call_line INTEGER
                    )
                    """
                )
                conn.execute("DELETE FROM _stg_edges")
                conn.execute(
                    f"""
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
                    """
                )
                conn.execute(
                    """
                    UPDATE edges
                    SET weight = stg.weight,
                        call_line = COALESCE(stg.call_line, edges.call_line)
                    FROM (
                        SELECT DISTINCT ON (source, target, relation) source, target, relation, weight, call_line
                        FROM _stg_edges
                    ) stg
                    WHERE edges.source = stg.source AND edges.target = stg.target AND edges.relation = stg.relation
                    """
                )
                conn.execute(
                    """
                    INSERT INTO edges (source, target, relation, weight, call_line)
                    SELECT DISTINCT ON (source, target, relation) source, target, relation, weight, call_line
                    FROM _stg_edges stg
                    WHERE NOT EXISTS (
                        SELECT 1 FROM edges e
                        WHERE e.source = stg.source AND e.target = stg.target AND e.relation = stg.relation
                    )
                    """
                )
                conn.execute("DROP TABLE IF EXISTS _stg_edges")

    def get_edges(
        self,
        source: Optional[str] = None,
        sources: Optional[List[str]] = None,
        target: Optional[str] = None,
        targets: Optional[List[str]] = None,
        symbol: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Queries edges matching optional source(s), target(s), incident symbol, or relation filters."""
        query = "SELECT source, target, relation, weight, call_line FROM edges WHERE 1=1"
        params: List[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if sources is not None:
            if not sources:
                return []
            query += " AND source IN (SELECT UNNEST(?::VARCHAR[]))"
            params.append(list(sources))
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
        headers = ["symbol", "filepath", "start_line", "start_col", "end_line", "end_col", "role"]
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
                conn.execute(
                    f"""
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
                    """
                )

    def get_definitions_map(self) -> Dict[str, Dict[str, Any]]:
        """Returns all definition occurrences as {symbol: {filepath, start_line, ...}} in one query."""
        res = self._fetch_all(
            """
            SELECT symbol, filepath, start_line, start_col, end_line, end_col, role
            FROM occurrences
            WHERE (role & 1) = 1
            """
        )
        return {
            r["symbol"]: {
                "filepath": r["filepath"],
                "start_line": r["start_line"],
                "start_col": r["start_col"],
                "end_line": r["end_line"],
                "end_col": r["end_col"],
                "role": r["role"],
            }
            for r in res
        }

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
        """Deletes edges and occurrences whose symbols no longer exist via linear anti-joins."""
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
