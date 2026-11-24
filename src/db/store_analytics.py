import logging
from typing import Any, Dict, List, Optional

from db.base import BaseRepository, normalize_path
from engines.polymorphism import (
    IMPLEMENTS_RELATION,
    POLYMORPHIC_KINDS,
    VIRTUAL_DISPATCH_RELATION,
)

logger = logging.getLogger(__name__)
_POLY_KINDS_LIST = sorted(POLYMORPHIC_KINDS)


class AnalyticsStore(BaseRepository):
    """
    Domain store providing read-only analytical queries, graph intelligence summaries,
    symmetrical transitive closures, and clustering graph projections.
    """

    def get_symbol_counts_by_kind(self) -> Dict[str, int]:
        """Returns symbol counts grouped by their declaration kind."""
        rows = self._fetch_all("SELECT kind, COUNT(*) AS cnt FROM symbols GROUP BY kind")
        return {r["kind"]: int(r["cnt"]) for r in rows}

    def get_repo_totals(self) -> Dict[str, int]:
        """Returns total counts for files, symbols, edges, occurrences, and violations."""
        files_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM files") or {}).get("cnt", 0)
        symbols_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM symbols") or {}).get("cnt", 0)
        edges_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM edges") or {}).get("cnt", 0)
        violations_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM compliance_violations") or {}).get("cnt", 0)
        occ_cnt = (self._fetch_one("SELECT COUNT(*) AS cnt FROM occurrences") or {}).get("cnt", 0)
        return {
            "files": int(files_cnt),
            "symbols": int(symbols_cnt),
            "edges": int(edges_cnt),
            "violations": int(violations_cnt),
            "occurrences": int(occ_cnt),
        }

    def get_compliance_summary(self, top_files: int = 5) -> Dict[str, Any]:
        """
        Returns a read-only aggregated compliance scorecard directly from DuckDB:
        file posture, normalized severity counts, origin split, per-rule rollups,
        and top offending files (excluding pending_audit markers from rule counts).
        """
        posture_row = self._fetch_one(
            """
            SELECT
                COUNT(*) AS total_files,
                COALESCE(SUM(CASE WHEN status = 'COMPLIANT' THEN 1 ELSE 0 END), 0) AS compliant_files,
                COALESCE(SUM(CASE WHEN status <> 'COMPLIANT' THEN 1 ELSE 0 END), 0) AS violating_files,
                COALESCE(SUM(CASE WHEN pending_audit = TRUE THEN 1 ELSE 0 END), 0) AS pending_audit,
                COALESCE(SUM(CASE WHEN manual_status <> status THEN 1 ELSE 0 END), 0) AS manual_overrides
            FROM files
            """
        ) or {}

        rule_rows = self._fetch_all(
            """
            SELECT
                COALESCE(v.rule_id, 'unknown') AS rule_id,
                COALESCE(
                    r.severity,
                    CASE WHEN COALESCE(v.origin, 'automatic') = 'manual' THEN 'Manual' ELSE 'Warning' END
                ) AS severity,
                COALESCE(
                    r.description,
                    CASE WHEN COALESCE(v.origin, 'automatic') = 'manual'
                         THEN 'Manual logical audit finding'
                         ELSE 'Architectural boundary rule' END
                ) AS description,
                COALESCE(v.origin, 'automatic') AS origin,
                COUNT(*) AS hit_count,
                COUNT(DISTINCT v.filepath) AS file_count
            FROM compliance_violations v
            LEFT JOIN compliance_rules r ON v.rule_id = r.rule_id
            WHERE COALESCE(v.rule_id, '') <> 'pending_audit'
            GROUP BY 1, 2, 3, 4
            ORDER BY hit_count DESC, rule_id ASC
            """
        )

        file_rows = self._fetch_all(
            """
            SELECT filepath, COUNT(*) AS hit_count
            FROM compliance_violations
            WHERE COALESCE(rule_id, '') <> 'pending_audit'
            GROUP BY filepath
            ORDER BY hit_count DESC, filepath ASC
            LIMIT ?
            """,
            (int(top_files),),
        )

        def _norm_severity(raw: Any) -> str:
            val = str(raw or "Warning").strip().lower()
            mapping = {
                "critical": "Critical",
                "error": "Error",
                "warning": "Warning",
                "info": "Info",
                "manual": "Manual",
            }
            return mapping.get(val, val.capitalize() if val else "Warning")

        by_severity: Dict[str, int] = {}
        merged_rules: Dict[str, Dict[str, Any]] = {}
        total_violations = 0
        automatic_violations = 0
        manual_violations = 0

        for r in rule_rows:
            hits = int(r.get("hit_count") or 0)
            sev = _norm_severity(r.get("severity"))
            origin = str(r.get("origin") or "automatic").lower()
            rid = str(r.get("rule_id") or "unknown")
            desc = str(r.get("description") or "").strip()
            f_cnt = int(r.get("file_count") or 0)

            total_violations += hits
            if origin == "manual":
                manual_violations += hits
            else:
                automatic_violations += hits

            by_severity[sev] = by_severity.get(sev, 0) + hits

            if rid not in merged_rules:
                merged_rules[rid] = {
                    "rule_id": rid,
                    "severity": sev,
                    "description": desc,
                    "count": hits,
                    "file_count": f_cnt,
                }
            else:
                merged_rules[rid]["count"] += hits
                merged_rules[rid]["file_count"] = max(merged_rules[rid]["file_count"], f_cnt)

        by_rule = sorted(merged_rules.values(), key=lambda x: (-x["count"], x["rule_id"]))
        hotspot_files = [
            {"filepath": normalize_path(r["filepath"]), "count": int(r.get("hit_count") or 0)}
            for r in file_rows
            if r.get("filepath")
        ]

        return {
            "total_files": int(posture_row.get("total_files") or 0),
            "compliant_files": int(posture_row.get("compliant_files") or 0),
            "violating_files": int(posture_row.get("violating_files") or 0),
            "pending_audit": int(posture_row.get("pending_audit") or 0),
            "manual_overrides": int(posture_row.get("manual_overrides") or 0),
            "total_violations": total_violations,
            "automatic_violations": automatic_violations,
            "manual_violations": manual_violations,
            "by_severity": by_severity,
            "by_rule": by_rule,
            "hotspot_files": hotspot_files,
        }

    def get_symbol_count_by_languages(self, languages: List[str]) -> int:
        """Returns the count of symbols originating from files of specific languages."""
        if not languages:
            return 0
        row = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM symbols WHERE filepath IN (SELECT filepath FROM files WHERE language IN (SELECT UNNEST(?::VARCHAR[])))",
            (languages,),
        )
        return int(row["cnt"]) if row else 0

    def get_transitive_closure(
        self,
        symbol: str,
        max_depth: int = 4,
        direction: str = "both",
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Symmetrical BFS graph traversal finding upstream (callers) and/or downstream (callees) symbols.
        Expands polymorphic Implements edges bidirectionally as VirtualDispatch without sibling leakage.
        """
        upstream: List[Dict[str, Any]] = []
        downstream: List[Dict[str, Any]] = []
        dir_norm = (direction or "both").lower()

        if dir_norm in ("upstream", "both"):
            visited = {symbol}
            current_frontier = {symbol: [symbol]}
            for depth in range(max_depth):
                if not current_frontier:
                    break
                nodes = list(current_frontier.keys())
                # Standard callers (exclude Implements so abstract T does not bounce to sibling concrete classes)
                direct_rows = self._fetch_all(
                    "SELECT source AS next_sym, target AS curr_sym, relation FROM edges WHERE target IN (SELECT UNNEST(?::VARCHAR[])) AND relation <> ?",
                    (nodes, IMPLEMENTS_RELATION),
                )
                # Virtual dispatch upstream: concrete C --[Implements]--> abstract T
                virtual_rows = self._fetch_all(
                    """SELECT e.target AS next_sym, e.source AS curr_sym, ? AS relation
                       FROM edges e
                       WHERE e.source IN (SELECT UNNEST(?::VARCHAR[]))
                         AND e.relation = ?""",
                    (VIRTUAL_DISPATCH_RELATION, nodes, IMPLEMENTS_RELATION),
                )
                next_frontier = {}
                for r in direct_rows + virtual_rows:
                    caller, curr, rel = r["next_sym"], r["curr_sym"], r["relation"]
                    if caller not in visited:
                        visited.add(caller)
                        new_path = [caller] + current_frontier[curr]
                        upstream.append({
                            "symbol": caller,
                            "parent": curr,
                            "depth": depth + 1,
                            "path": new_path,
                            "relation": rel,
                        })
                        next_frontier[caller] = new_path
                current_frontier = next_frontier

        if dir_norm in ("downstream", "both"):
            visited = {symbol}
            current_frontier = {symbol: [symbol]}
            for depth in range(max_depth):
                if not current_frontier:
                    break
                nodes = list(current_frontier.keys())
                # Standard callees (exclude Implements so concrete C does not bounce through T to siblings)
                direct_rows = self._fetch_all(
                    "SELECT target AS next_sym, source AS curr_sym, relation FROM edges WHERE source IN (SELECT UNNEST(?::VARCHAR[])) AND relation <> ?",
                    (nodes, IMPLEMENTS_RELATION),
                )
                # Virtual dispatch downstream: abstract T (in POLYMORPHIC_KINDS) <--[Implements]-- concrete C
                virtual_rows = self._fetch_all(
                    """SELECT e.source AS next_sym, e.target AS curr_sym, ? AS relation
                       FROM edges e
                       JOIN symbols s ON e.target = s.symbol
                       WHERE e.target IN (SELECT UNNEST(?::VARCHAR[]))
                         AND e.relation = ?
                         AND s.kind IN (SELECT UNNEST(?::VARCHAR[]))""",
                    (VIRTUAL_DISPATCH_RELATION, nodes, IMPLEMENTS_RELATION, _POLY_KINDS_LIST),
                )
                next_frontier = {}
                for r in direct_rows + virtual_rows:
                    callee, curr, rel = r["next_sym"], r["curr_sym"], r["relation"]
                    if callee not in visited:
                        visited.add(callee)
                        new_path = current_frontier[curr] + [callee]
                        downstream.append({
                            "symbol": callee,
                            "parent": curr,
                            "depth": depth + 1,
                            "path": new_path,
                            "relation": rel,
                        })
                        next_frontier[callee] = new_path
                current_frontier = next_frontier

        return {"upstream": upstream, "downstream": downstream}

    def get_graph_snapshot_data(self) -> Dict[str, Any]:
        """Consolidates workspace summary stats for graph ingestion."""
        totals = self.get_repo_totals()
        def_row = self._fetch_one("SELECT COUNT(*) AS cnt FROM symbols WHERE start_line IS NOT NULL")
        return {
            "files_count": totals["files"],
            "symbols_count": totals["symbols"],
            "edges_count": totals["edges"],
            "occurrences_count": totals["occurrences"],
            "definitions_count": int(def_row["cnt"]) if def_row else 0,
            "references_count": totals["occurrences"],
        }

    def get_cluster_graph_data(
        self,
        language: Optional[str] = None,
        scope_prefixes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a read-only DuckDB projection over canonical symbols, files, and edges
        for parameter-free hierarchical clustering.
        """
        norm_prefixes = (
            [p.replace("\\", "/").rstrip("/") for p in scope_prefixes if p]
            if scope_prefixes
            else None
        )

        symbols_sql = """
            SELECT
                s.symbol,
                s.name,
                s.filepath,
                s.kind,
                s.parent_symbol,
                s.start_line,
                f.language
            FROM symbols s
            JOIN files f ON s.filepath = f.filepath
            WHERE s.filepath IS NOT NULL
              AND NOT starts_with(s.symbol, 'local ')
              AND COALESCE(s.kind, '') NOT IN ('Parameter', 'Module', 'Package', 'TypeParameter')
              AND (? IS NULL OR f.language = ?)
              AND (?::VARCHAR[] IS NULL OR EXISTS (
                    SELECT 1 FROM UNNEST(?::VARCHAR[]) AS p(prefix)
                    WHERE s.filepath = p.prefix OR starts_with(s.filepath, p.prefix || '/')
                  ))
        """
        symbols = self._fetch_all(symbols_sql, (language, language, norm_prefixes, norm_prefixes))

        edges_sql = """
            SELECT
                e.source,
                e.target,
                e.relation,
                e.weight,
                s_src.filepath AS src_filepath,
                s_tgt.filepath AS tgt_filepath,
                s_tgt.name AS tgt_name,
                s_tgt.kind AS tgt_kind
            FROM edges e
            JOIN symbols s_src ON e.source = s_src.symbol
            JOIN symbols s_tgt ON e.target = s_tgt.symbol
            WHERE e.source <> e.target
              AND NOT starts_with(e.source, 'local ')
              AND NOT starts_with(e.target, 'local ')
              AND s_src.filepath IS NOT NULL
              AND s_tgt.filepath IS NOT NULL
        """
        edges = self._fetch_all(edges_sql)
        return {"symbols": symbols, "edges": edges}
