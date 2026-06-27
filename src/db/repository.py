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
        """Registers or updates a file's hashing and index metadata."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO files (filepath, sha256, language, last_indexed)
                VALUES (?, ?, ?, now())
                ON CONFLICT (filepath) DO UPDATE SET
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
                "SELECT filepath, sha256, language, last_indexed FROM files WHERE filepath = ?",
                (filepath,)
            ).fetchone()
            if res:
                return {
                    "filepath": res[0],
                    "sha256": res[1],
                    "language": res[2],
                    "last_indexed": res[3]
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
        message: str
    ):
        """Registers an architectural boundary violation."""
        with self.db_conn.session() as conn:
            conn.execute(
                """
                INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (violation_id) DO UPDATE SET
                    rule_id = excluded.rule_id,
                    symbol = excluded.symbol,
                    filepath = excluded.filepath,
                    line = excluded.line,
                    message = excluded.message
                """,
                (violation_id, rule_id, symbol, filepath, line, message)
            )

    def get_violations(self) -> List[Dict[str, Any]]:
        """Retrieves all registered compliance violations sorted by threat severity."""
        with self.db_conn.session() as conn:
            res = conn.execute(
                """
                SELECT v.violation_id, v.rule_id, r.description, v.symbol, v.filepath, v.line, v.message, r.severity, v.checked_at
                FROM compliance_violations v
                JOIN compliance_rules r ON v.rule_id = r.rule_id
                ORDER BY r.severity DESC, v.filepath ASC
                """
            ).fetchall()
            return [
                {
                    "violation_id": r[0],
                    "rule_id": r[1],
                    "rule_description": r[2],
                    "symbol": r[3],
                    "filepath": r[4],
                    "line": r[5],
                    "message": r[6],
                    "severity": r[7],
                    "checked_at": r[8]
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
                    array_cosine_similarity(embedding, ?::FLOAT[]) as similarity
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
        """Bulk upserts a list of files in a single transaction."""
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
                INSERT INTO files (filepath, sha256, language, last_indexed)
                VALUES (?, ?, ?, now())
                ON CONFLICT (filepath) DO UPDATE SET
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

