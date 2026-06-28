from pathlib import Path
from typing import Dict, List, Any, Optional
from db.connection import DbConnection

class Repository:
    """
    Data Access Object (DAO) for the Arch-mcp DuckDB database.
    Exposes unified methods for symbols, occurrences, edges, and compliance tracking.
    """

    def __init__(self, db_conn: DbConnection):
        self.db_conn = db_conn

    # --- File Tracking & Integrity Cascade ---
    
    def upsert_file(self, filepath: str, sha256: str, language: str):
        """Registers or updates a file's hashing and index metadata. Resets manual_status if changed."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO files (filepath, sha256, language, last_indexed, status, manual_status, manual_fields, justification)
                VALUES (?, ?, ?, now(), 'COMPLIANT', 'PENDING_AUDIT', '{}', 'New file, pending initial audit')
                ON CONFLICT (filepath) DO UPDATE SET
                    manual_status = CASE WHEN files.sha256 <> excluded.sha256 THEN 'PENDING_AUDIT' ELSE files.manual_status END,
                    justification = CASE WHEN files.sha256 <> excluded.sha256 THEN 'File modified, pending re-audit' ELSE files.justification END,
                    sha256 = excluded.sha256,
                    language = excluded.language,
                    last_indexed = now()
                """,
                (filepath, sha256, language)
            )

    def delete_file(self, filepath: str):
        """
        Deletes a file record and manually cleans up associated symbols, occurrences, and edges
        to maintain referential integrity.
        """
        with self.db_conn.session() as conn:
            # 1. Delete outgoing or incoming edges linking to symbols in this file
            conn.execute(
                """
                DELETE FROM edges 
                WHERE source IN (SELECT symbol FROM symbols WHERE filepath = ?)
                   OR target IN (SELECT symbol FROM symbols WHERE filepath = ?)
                """,
                (filepath, filepath)
            )
            # 2. Delete occurrences in this file
            conn.execute("DELETE FROM occurrences WHERE filepath = ?", (filepath,))
            # 3. Delete symbols in this file
            conn.execute("DELETE FROM symbols WHERE filepath = ?", (filepath,))
            # 4. Delete the file itself
            conn.execute("DELETE FROM files WHERE filepath = ?", (filepath,))

    def get_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Retrieves indexing metadata for a specific file."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath, sha256, language, last_indexed, status, manual_status, manual_fields, justification FROM files WHERE filepath = ?",
                (filepath,)
            ).fetchone()
            if res:
                return {
                    "filepath": res[0],
                    "sha256": res[1],
                    "language": res[2],
                    "last_indexed": res[3],
                    "status": res[4],
                    "manual_status": res[5],
                    "manual_fields": res[6],
                    "justification": res[7]
                }
        return None

    # --- Symbols & Declarations ---

    def upsert_symbol(
        self,
        symbol: str,
        filepath: Optional[str],
        kind: str,
        signature: Optional[str],
        docstring: Optional[str],
        body_hash: Optional[str],
        embedding: Optional[List[float]] = None
    ):
        """
        Inserts or replaces a code symbol declaration in the database.
        filepath is optional (NULL for external third-party library dependencies).
        """
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    filepath = excluded.filepath,
                    kind = excluded.kind,
                    signature = excluded.signature,
                    docstring = excluded.docstring,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding
                """,
                (symbol, filepath, kind, signature, docstring, body_hash, embedding)
            )

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a registered symbol declaration."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash FROM symbols WHERE symbol = ?",
                (symbol,)
            ).fetchone()
            if res:
                return {
                    "symbol": res[0],
                    "filepath": res[1],
                    "kind": res[2],
                    "signature": res[3],
                    "docstring": res[4],
                    "body_hash": res[5]
                }
        return None

    # --- Symbol Occurrences (Coordinates) ---

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
        """
        Registers a reference or definition coordinate occurrence of a symbol.
        """
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, filepath, start_line, start_col, end_line, end_col, role)
            )

    def get_occurrences_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Lists all physical coordinates where a symbol occurs/is used."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath, start_line, start_col, end_line, end_col, role FROM occurrences WHERE symbol = ?",
                (symbol,)
            ).fetchall()
            return [
                {
                    "filepath": r[0],
                    "start_line": r[1],
                    "start_col": r[2],
                    "end_line": r[3],
                    "end_col": r[4],
                    "role": r[5]
                }
                for r in res
            ]

    # --- Call Graph & Relational Edges ---

    def add_edge(self, source: str, target: str, relation: str):
        """Registers a structural call or dependency link between two symbols."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO edges (source, target, relation)
                VALUES (?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (source, target, relation)
            )

    def get_outgoing_edges(self, symbol: str) -> List[Dict[str, str]]:
        """Lists all symbols directly referenced/called by the given symbol."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT target, relation FROM edges WHERE source = ?",
                (symbol,)
            ).fetchall()
            return [{"target": r[0], "relation": r[1]} for r in res]

    def get_incoming_edges(self, symbol: str) -> List[Dict[str, str]]:
        """Lists all callers/parents referencing the given symbol (backreferences)."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT source, relation FROM edges WHERE target = ?",
                (symbol,)
            ).fetchall()
            return [{"source": r[0], "relation": r[1]} for r in res]

    # --- Compliance Policies & Auditing ---

    def upsert_compliance_rule(self, rule_id: str, description: str, severity: str):
        """Stores or updates an architectural safety boundary rule."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO compliance_rules (rule_id, description, severity)
                VALUES (?, ?, ?)
                ON CONFLICT (rule_id) DO UPDATE SET
                    description = excluded.description,
                    severity = excluded.severity
                """,
                (rule_id, description, severity)
            )

    def add_violation(
        self,
        violation_id: str,
        rule_id: str,
        symbol: Optional[str],
        filepath: str,
        line: int,
        message: str,
        origin: str = "automatic"
    ):
        """Registers an architectural boundary violation."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (violation_id) DO UPDATE SET
                    rule_id = excluded.rule_id,
                    symbol = excluded.symbol,
                    filepath = excluded.filepath,
                    line = excluded.line,
                    message = excluded.message,
                    origin = excluded.origin
                """,
                (violation_id, rule_id, symbol, filepath, line, message, origin)
            )

    def get_violations(self) -> List[Dict[str, Any]]:
        """Retrieves all registered compliance violations sorted by threat severity."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT v.violation_id, v.rule_id, r.description, v.symbol, v.filepath, v.line, v.message, r.severity, v.checked_at, v.origin
                FROM compliance_violations v
                LEFT JOIN compliance_rules r ON v.rule_id = r.rule_id
                ORDER BY r.severity DESC, v.filepath ASC
                """
            ).fetchall()
            return [
                {
                    "violation_id": r[0],
                    "rule_id": r[1],
                    "rule_description": r[2] or "Manual Logical Audit",
                    "symbol": r[3],
                    "filepath": r[4],
                    "line": r[5],
                    "message": r[6],
                    "severity": r[7] or "WARNING",
                    "checked_at": r[8],
                    "origin": r[9]
                }
                for r in res
            ]

    # --- Vector Similarity Search ---

    def semantic_search(self, query_embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """
        Runs a cosine similarity vector search over the docstrings of code symbols.
        """
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT 
                    symbol, 
                    filepath, 
                    kind, 
                    signature, 
                    docstring,
                    list_cosine_similarity(embedding, ?::FLOAT[]) as similarity
                FROM symbols
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT ?
                """,
                (query_embedding, limit)
            ).fetchall()
            
            return [
                {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "similarity": r[5]
                }
                for r in res
            ]

    # --- Bulk Ingestion Helpers ---

    def upsert_files_bulk(self, files_list: List[Dict[str, Any]]):
        """Bulk upserts a list of files in a single transaction. Resets manual_status on change."""
        data = [
            (
                f["filepath"],
                f["sha256"],
                f["language"]
            )
            for f in files_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO files (filepath, sha256, language, last_indexed, status, manual_status, manual_fields, justification)
                VALUES (?, ?, ?, now(), 'COMPLIANT', 'PENDING_AUDIT', '{}', 'New file, pending initial audit')
                ON CONFLICT (filepath) DO UPDATE SET
                    manual_status = CASE WHEN files.sha256 <> excluded.sha256 THEN 'PENDING_AUDIT' ELSE files.manual_status END,
                    justification = CASE WHEN files.sha256 <> excluded.sha256 THEN 'File modified, pending re-audit' ELSE files.justification END,
                    sha256 = excluded.sha256,
                    language = excluded.language,
                    last_indexed = now()
                """,
                data
            )

    def upsert_symbols_bulk(self, symbols_list: List[Dict[str, Any]]):
        """Bulk upserts a list of symbols in a single transaction."""
        data = [
            (
                sym["symbol"],
                sym["filepath"],
                sym["kind"],
                sym["signature"],
                sym["docstring"],
                sym["body_hash"],
                sym.get("embedding")
            )
            for sym in symbols_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol) DO UPDATE SET
                    filepath = excluded.filepath,
                    kind = excluded.kind,
                    signature = excluded.signature,
                    docstring = excluded.docstring,
                    body_hash = excluded.body_hash,
                    embedding = excluded.embedding
                """,
                data
            )

    def add_occurrences_bulk(self, occurrences_list: List[Dict[str, Any]]):
        """Bulk inserts a list of occurrences in a single transaction."""
        data = [
            (
                occ["symbol"],
                occ["filepath"],
                occ["start_line"],
                occ["start_col"],
                occ["end_line"],
                occ["end_col"],
                occ["role"]
            )
            for occ in occurrences_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                data
            )

    def add_edges_bulk(self, edges_list: List[Dict[str, Any]]):
        """Bulk inserts a list of edges in a single transaction."""
        data = [
            (
                edge["source"],
                edge["target"],
                edge["relation"]
            )
            for edge in edges_list
        ]
        with self.db_conn.session() as conn:
            conn.executemany(
                """
                INSERT INTO edges (source, target, relation)
                VALUES (?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                data
            )

    def get_symbols_in_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Retrieves all symbols defined inside a specific file."""
        normalized = filepath.replace("\\", "/")
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT symbol, filepath, kind, signature, docstring, body_hash
                FROM symbols
                WHERE replace(filepath, '\\', '/') = ? OR filepath = ?
                """,
                (normalized, filepath)
            ).fetchall()
            return [
                {
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4],
                    "body_hash": r[5]
                }
                for r in res
            ]

    def get_transitive_closure(self, symbol: str, max_depth: int = 3) -> Dict[str, List[Dict[str, Any]]]:
        """
        Computes the transitive closure of callers (upstream) and callees (downstream)
        for a given symbol up to max_depth.
        Returns a dict: {"upstream": [...], "downstream": [...]}
        """
        upstream = []
        downstream = []

        with self.db_conn.session() as conn:
            # Upstream BFS (incoming callers)
            queue = [(symbol, 0, [symbol])]
            visited = {symbol}
            while queue:
                curr, depth, path = queue.pop(0)
                if depth >= max_depth:
                    continue
                callers = conn.execute(
                    "SELECT source FROM edges WHERE target = ?", (curr,)
                ).fetchall()
                for (caller,) in callers:
                    if caller not in visited:
                        visited.add(caller)
                        new_path = [caller] + path
                        upstream.append({
                            "symbol": caller,
                            "depth": depth + 1,
                            "path": new_path
                        })
                        queue.append((caller, depth + 1, new_path))

            # Downstream BFS (outgoing callees)
            queue = [(symbol, 0, [symbol])]
            visited = {symbol}
            while queue:
                curr, depth, path = queue.pop(0)
                if depth >= max_depth:
                    continue
                callees = conn.execute(
                    "SELECT target FROM edges WHERE source = ?", (curr,)
                ).fetchall()
                for (callee,) in callees:
                    if callee not in visited:
                        visited.add(callee)
                        new_path = path + [callee]
                        downstream.append({
                            "symbol": callee,
                            "depth": depth + 1,
                            "path": new_path
                        })
                        queue.append((callee, depth + 1, new_path))

        return {"upstream": upstream, "downstream": downstream}

    def get_symbol_counts_by_kind(self) -> Dict[str, int]:
        """Returns symbol counts grouped by their declaration kind."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT kind, COUNT(*) FROM symbols GROUP BY kind"
            ).fetchall()
            return {r[0]: r[1] for r in res}

    def get_repo_totals(self) -> Dict[str, int]:
        """Returns total counts for files, symbols, edges, and violations."""
        with self.db_conn.session() as conn:
            files_cnt = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            symbols_cnt = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            edges_cnt = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            violations_cnt = conn.execute("SELECT COUNT(*) FROM compliance_violations").fetchone()[0]
            return {
                "files": files_cnt,
                "symbols": symbols_cnt,
                "edges": edges_cnt,
                "violations": violations_cnt
            }

    def get_symbols_by_file_prefix(self) -> Dict[str, int]:
        """Groups symbol counts by their top-level directory prefix."""
        prefix_counts = {}
        with self.db_conn.session() as conn:
            res = conn.execute(
                "SELECT filepath FROM symbols WHERE filepath IS NOT NULL"
            ).fetchall()
            for (fp,) in res:
                fp_norm = fp.replace("\\", "/")
                parts = fp_norm.split("/")
                if len(parts) > 1:
                    if len(parts) >= 3:
                        prefix = f"{parts[0]}/{parts[1]}/"
                    else:
                        prefix = f"{parts[0]}/"
                else:
                    prefix = "./"
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        return prefix_counts

    def update_file_manual_status(self, filepath: str, status: str, justification: Optional[str] = None):
        """Sets the manual compliance status for a file."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET manual_status = ?,
                    justification = ?
                WHERE filepath = ?
                """,
                (status, justification, filepath)
            )

    def update_file_manual_fields(self, filepath: str, manual_fields: dict, justification: Optional[str] = None):
        """Sets or updates the manual metadata fields (JSON format) for a file."""
        import json
        fields_str = json.dumps(manual_fields)
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET manual_fields = ?,
                    justification = ?
                WHERE filepath = ?
                """,
                (fields_str, justification, filepath)
            )

    def update_file_status(self, filepath: str, status: str):
        """Updates the automatically evaluated compliance status for a file."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                UPDATE files
                SET status = ?
                WHERE filepath = ?
                """,
                (status, filepath)
            )

    def get_all_files_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves all files' status, manual status, manual fields and justification."""
        import json
        with self.db_conn.session() as conn:
            rows = conn.execute(
                "SELECT filepath, status, manual_status, manual_fields, justification FROM files"
            ).fetchall()
            metadata = {}
            for r in rows:
                try:
                    manual_fields = json.loads(r[3]) if r[3] else {}
                except Exception:
                    manual_fields = {}
                metadata[r[0]] = {
                    "filepath": r[0],
                    "status": r[1],
                    "manual_status": r[2],
                    "manual_fields": manual_fields,
                    "justification": r[4]
                }
            return metadata

    def delete_manual_violations(self, filepath: str):
        """Clears manual violations for a file."""
        with self.db_conn.session() as conn:
            conn.execute(
                "DELETE FROM compliance_violations WHERE filepath = ? AND origin = 'manual'",
                (filepath,)
            )



