"""
Database Reader Module.
Focused strictly on DuckDB connection lifecycle and query delegation to domain stores.
Delegates SCIP and signature parsing to `ScipParser`.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import duckdb

from db.connection import DbConnection
from db.repository import Repository
from .scip_parser import ScipParser


class DatabaseReader:
    """
    Reads workspace intelligence from DuckDB via repository stores and DbConnection.
    """

    def __init__(self, db_path: str = ".arch/arch.db", repository: Optional[Repository] = None, db_conn: Optional[DbConnection] = None):
        if repository is not None:
            self.repository = repository
            self.db_conn = repository.db_conn
            self.db_path = str(self.db_conn.db_path)
            self._own_conn = False
        elif db_conn is not None:
            self.db_conn = db_conn
            self.db_path = str(self.db_conn.db_path)
            self.repository = Repository(self.db_conn)
            self._own_conn = False
        else:
            if not os.path.exists(db_path):
                candidates = [
                    db_path,
                    os.path.join(".arch", "arch.db"),
                    os.path.join("..", ".arch", "arch.db"),
                    "arch.db",
                ]
                found = None
                for cand in candidates:
                    if os.path.exists(cand):
                        found = cand
                        break
                if not found:
                    raise FileNotFoundError(
                        f"Database not found at '{db_path}'. Checked candidates: {candidates}"
                    )
                self.db_path = found
            else:
                self.db_path = db_path

            self.db_conn = DbConnection(Path(self.db_path))
            self.repository = Repository(self.db_conn)
            self._own_conn = True

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Returns the active DuckDB connection from DbConnection."""
        return self.db_conn.get_connection()

    def close(self):
        """Closes the connection if owned by this instance."""
        if getattr(self, "_own_conn", False) and self.db_conn is not None:
            self.db_conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Backwards-compatible static delegates
    parse_signature_ports = staticmethod(ScipParser.parse_signature_ports)
    parse_scip_symbol = staticmethod(ScipParser.parse_scip_symbol)

    def fetch_files(self) -> List[Dict[str, Any]]:
        """Fetches all tracked files using the workspace store."""
        raw_files = self.repository.workspace.get_all_files()
        files = []
        for f in raw_files:
            fp = f["filepath"]
            files.append({
                "filepath": fp,
                "language": f.get("language") or "python",
                "status": f.get("status") or "COMPLIANT",
                "sha256": f.get("sha256"),
                "filename": os.path.basename(fp),
                "directory": os.path.dirname(fp) or ".",
            })
        return files

    def fetch_symbols(self) -> List[Dict[str, Any]]:
        """Fetches all symbols using the graph store and parses them with ScipParser."""
        raw_files = self.repository.workspace.get_all_files()
        known_files = {f["filepath"] for f in raw_files if f.get("filepath")}
        raw_symbols = self.repository.graph.get_all_symbols()

        symbols = []
        for sym in raw_symbols:
            raw_sym = sym["symbol"]
            filepath = sym.get("filepath")
            kind = sym.get("kind") or "Symbol"
            signature = sym.get("signature")
            docstring = sym.get("docstring")
            conn_weight = sym.get("connection_weight") or 0
            code_block = sym.get("code_block")
            clean_sym = sym.get("clean_symbol")

            parsed = ScipParser.parse_scip_symbol(raw_sym, filepath=filepath, known_files=known_files, clean_symbol=clean_sym)
            ports = ScipParser.parse_signature_ports(docstring, signature)
            symbols.append({
                "symbol": raw_sym,
                "clean_symbol": clean_sym,
                "filepath": filepath,
                "kind": kind,
                "signature": signature,
                "docstring": docstring,
                "connection_weight": conn_weight,
                "label": parsed["label"],
                "display_name": parsed["display_name"],
                "pkg": parsed["pkg"],
                "is_local": parsed["is_local"],
                "is_external": parsed["is_external"],
                "is_parameter": parsed.get("is_parameter", False),
                "ports": ports,
                "code_block": code_block,
            })
        return symbols

    def fetch_symbol_definitions(self) -> Dict[str, Dict[str, Any]]:
        """Fetches definition line numbers and locations for symbols from occurrences."""
        return self.repository.graph.get_definitions_map()

    def fetch_edges(self) -> List[Dict[str, Any]]:
        """Fetches edges with call line locations joined from occurrences/call_line."""
        with self.db_conn.session() as conn:
            query = """
                SELECT e.source, e.target, e.relation, e.weight,
                       COALESCE(e.call_line, o.start_line) AS line, o.start_col AS col
                FROM edges e
                LEFT JOIN symbols s ON e.source = s.symbol
                LEFT JOIN occurrences o ON e.target = o.symbol AND s.filepath = o.filepath
            """
            rows = conn.execute(query).fetchall()

        edges = []
        for row in rows:
            line = int(row[4]) if row[4] is not None else None
            col = int(row[5]) if row[5] is not None else None
            edges.append({
                "source": row[0],
                "target": row[1],
                "relation": row[2] or "Calls",
                "weight": float(row[3]) if row[3] is not None else 1.0,
                "line": line,
                "col": col,
            })
        return edges

    def fetch_occurrences(
        self,
        filepath_filter: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches occurrences matching optional filepath filter."""
        with self.db_conn.session() as conn:
            query = """
                SELECT symbol, filepath, start_line, start_col, end_line, end_col, role
                FROM occurrences
            """
            params = []
            if filepath_filter:
                query += " WHERE filepath LIKE ?"
                norm_f = filepath_filter.replace("\\", "/")
                params.append(f"%{norm_f}%")

            query += " ORDER BY filepath, start_line, start_col"
            if limit:
                query += f" LIMIT {int(limit)}"

            rows = conn.execute(query, params).fetchall()

        occurrences = []
        for row in rows:
            filepath = row[1] if row[1] else "unknown"
            role = int(row[6])
            occurrences.append({
                "symbol": row[0],
                "filepath": filepath,
                "start_line": int(row[2]),
                "start_col": int(row[3]),
                "end_line": int(row[4]),
                "end_col": int(row[5]),
                "role": role,
                "is_definition": bool(role & 1),
                "is_reference": bool(role & 8),
                "is_import": bool(role & 2),
                "is_write": bool(role & 4),
            })
        return occurrences

    def get_summary_stats(self) -> Dict[str, Any]:
        """Returns workspace summary statistics from the analytics store."""
        return self.repository.analytics.get_graph_snapshot_data()
