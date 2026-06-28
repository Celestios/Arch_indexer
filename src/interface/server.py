import os
import sys
import json
from pathlib import Path
from typing import Optional, Union, List, Any

# Setup sys.path to resolve imports from src/
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import FastMCP
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor
from auditor.compiler import ContextCompiler
from engines.embedder import LocalEmbedder
from engines.communities import detect_communities

# Resolve the target project root (where the .arch/ database resides)
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    PROJECT_ROOT = Path(sys.argv[1]).resolve()
else:
    PROJECT_ROOT = Path(os.environ.get("ARCH_PROJECT_ROOT", os.getcwd())).resolve()

ARCH_DIR = PROJECT_ROOT / ".arch"
DB_PATH = ARCH_DIR / "arch.db"

# Initialize FastMCP Server
mcp = FastMCP("arch")


@mcp.tool()
def query(text: Union[List[str], str], limit: int = 5) -> str:
    """
    Runs keyword and semantic searches over symbols, docstrings, and files in the codebase.
    Accepts a single query string or a list of query strings, returning matches for each.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    # Force queries into a list
    queries = [text] if isinstance(text, str) else text

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)
    embedder = None

    try:
        bin_dir = src_dir.parent / "bin"
        embedder = LocalEmbedder(bin_dir)
    except Exception as e:
        db_conn.close()
        return f"Error: Could not initialize embedding engine: {e}"

    md = []
    try:
        for q in queries:
            # 1. Keyword search on symbol (nodes) names
            with db_conn.session() as conn:
                keyword_symbols = conn.execute(
                    "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE LOWER(symbol) LIKE ? LIMIT ?",
                    (f"%{q.lower()}%", limit)
                ).fetchall()
                
                # 2. Keyword search on filepaths
                file_matches = conn.execute(
                    "SELECT filepath, language, status FROM files WHERE LOWER(filepath) LIKE ? LIMIT ?",
                    (f"%{q.lower()}%", limit)
                ).fetchall()

            # 3. Semantic search over docstrings (vector similarity)
            results = []
            try:
                embedding = embedder.embed(q)
                results = repository.symbols.semantic_search(embedding, limit=limit)
            except Exception as e:
                # Fallback if embedding generation fails
                pass

            md.append(f"## Search Results for: \"{q}\"\n")
            
            # Section 1: Symbol Name Matches (Keyword)
            md.append("### 1. Symbol Name Matches (Keyword Search)")
            if not keyword_symbols:
                md.append("*No matching symbols found by name.*\n")
            else:
                for idx, row in enumerate(keyword_symbols, 1):
                    md.append(f"{idx}. **{row[0]}**")
                    md.append(f"   - **File**: `{row[1]}`")
                    md.append(f"   - **Kind**: `{row[2]}`")
                    if row[3]:
                        md.append(f"   - **Signature**: `{row[3]}`")
                md.append("")
                
            # Section 2: Semantic Matches (Docstrings)
            md.append("### 2. Semantic Docstring Matches")
            if not results:
                md.append("*No semantically matching symbols found in docstrings.*\n")
            else:
                for idx, res in enumerate(results, 1):
                    md.append(f"{idx}. **{res['symbol']}** (Similarity: {res['similarity']:.2f})")
                    md.append(f"   - **File**: `{res['filepath']}`")
                    md.append(f"   - **Kind**: `{res['kind']}`")
                    if res['docstring']:
                        doc = res['docstring'].strip().replace("\n", "\n     ")
                        md.append(f"   - **Doc**: {doc}")
                md.append("")
                
            # Section 3: Filepath Matches
            md.append("### 3. Filepath Matches")
            if not file_matches:
                md.append("*No matching files found by path.*\n")
            else:
                for idx, row in enumerate(file_matches, 1):
                    md.append(f"{idx}. **{row[0]}**")
                    md.append(f"   - **Language**: `{row[1]}`")
                    md.append(f"   - **Audit Status**: `{row[2]}`")
                md.append("")
    except Exception as e:
        return f"Error executing query search: {e}"
    finally:
        db_conn.close()

    return "\n".join(md)


@mcp.tool()
def context(filepaths: Union[List[str], str]) -> str:
    """
    Provides a compact structural index (Table of Contents) of all classes, methods,
    and functions declared in the specified file(s), along with their precise line ranges.
    Use this to locate specific definitions before reading the code.
    
    Accepts:
      - A single filepath string
      - A comma-separated filepath string (e.g. 'file1.dart, file2.dart')
      - A list/array of filepaths
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    # Normalize files to a list
    if isinstance(filepaths, str):
        if "," in filepaths:
            paths = [p.strip() for p in filepaths.split(",") if p.strip()]
        else:
            paths = [filepaths.strip()]
    else:
        paths = filepaths

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    out_md = []

    try:
        for fp in paths:
            symbols = repository.symbols.get_symbols_in_file(fp)
            # Resolve relative file name match if not found exactly
            if not symbols:
                all_files = repository.files.get_all_files_metadata()
                matched = None
                for real_fp in all_files.keys():
                    if real_fp.replace("\\", "/").endswith(fp.replace("\\", "/")):
                        matched = real_fp
                        break
                if matched:
                    fp = matched
                    symbols = repository.symbols.get_symbols_in_file(fp)

            if not symbols:
                out_md.append(f"## File Index: `{fp}`\n\n*No indexed symbols found in file. Make sure the file exists and is indexed.*")
                continue

            with db_conn.session() as conn:
                occs = conn.execute(
                    """
                    SELECT symbol, start_line, end_line, role 
                    FROM occurrences 
                    WHERE replace(filepath, '\\', '/') = ? OR filepath = ?
                    """,
                    (fp.replace("\\", "/"), fp)
                ).fetchall()

            # Map symbols to their occurrences (prefer role = 1: SCIP Definition)
            symbol_to_lines = {}
            for sym_name, start_line, end_line, role in occs:
                if sym_name not in symbol_to_lines or role == 1:
                    symbol_to_lines[sym_name] = (start_line, end_line)

            classes = []
            methods_and_funcs = []

            for sym in symbols:
                sym_name = sym["symbol"]
                line_range = ""
                if sym_name in symbol_to_lines:
                    start_line, end_line = symbol_to_lines[sym_name]
                    line_range = f"L{start_line}-{end_line}"

                sym_data = {
                    "symbol": sym_name,
                    "signature": sym["signature"],
                    "docstring": sym["docstring"],
                    "line_range": line_range,
                    "kind": sym["kind"]
                }

                if sym["kind"].lower() in ("class", "struct", "interface"):
                    classes.append(sym_data)
                else:
                    methods_and_funcs.append(sym_data)

            md = [f"## File Index: `{fp}`\n"]

            if classes:
                md.append("### Classes")
                for cl in classes:
                    range_str = f" [{cl['line_range']}]" if cl['line_range'] else ""
                    md.append(f"- **{cl['symbol']}**{range_str} ({cl['kind']})")
                    if cl['docstring']:
                        doc = cl['docstring'].strip().split("\n")[0]
                        md.append(f"  * {doc}")
                md.append("")

            if methods_and_funcs:
                md.append("### Methods & Functions")
                for mf in methods_and_funcs:
                    range_str = f" [{mf['line_range']}]" if mf['line_range'] else ""
                    md.append(f"- **{mf['symbol']}**{range_str}")
                    if mf['signature']:
                        md.append(f"  * *Signature*: `{mf['signature']}`")
                    if mf['docstring']:
                        doc = mf['docstring'].strip().split("\n")[0]
                        md.append(f"  * *Docstring*: {doc}")
                md.append("")

            out_md.append("\n".join(md))
    except Exception as e:
        return f"Error retrieving context: {e}"
    finally:
        db_conn.close()

    return "\n\n---\n\n".join(out_md)


@mcp.tool()
def impact(symbol: str, max_depth: int = 3) -> str:
    """
    Performs blast radius analysis for a symbol by computing the transitive closure
    of its upstream callers and downstream callees up to max_depth.
    Use this to see what will break if you modify this symbol's signature.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        closure = repository.edges.get_transitive_closure(symbol, max_depth=max_depth)
    except Exception as e:
        return f"Error computing blast radius: {e}"
    finally:
        db_conn.close()

    upstream = closure.get("upstream", [])
    downstream = closure.get("downstream", [])

    md = [f"## Blast Radius for: `{symbol}`\n"]

    md.append("### ── Upstream Callers (Who calls this?)")
    if not upstream:
        md.append("*No transitive upstream callers found.*")
    else:
        upstream_sorted = sorted(upstream, key=lambda x: x["depth"])
        for item in upstream_sorted:
            path_str = " ──> ".join(f"`{s.split('.')[-1]}`" for s in item["path"])
            md.append(f"- **{item['symbol']}** [Depth: {item['depth']}]")
            md.append(f"  * Path: {path_str}")
    md.append("")

    md.append("### ── Downstream Callees (What does this call?)")
    if not downstream:
        md.append("*No transitive downstream callees found.*")
    else:
        downstream_sorted = sorted(downstream, key=lambda x: x["depth"])
        for item in downstream_sorted:
            path_str = " ──> ".join(f"`{s.split('.')[-1]}`" for s in item["path"])
            md.append(f"- **{item['symbol']}** [Depth: {item['depth']}]")
            md.append(f"  * Path: {path_str}")
    md.append("")

    return "\n".join(md)


@mcp.tool()
def audit() -> str:
    """
    Runs the project-wide architectural boundary rules compliance audit.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)
    auditor = Auditor(repository, PROJECT_ROOT)

    try:
        # Run static compliance check (updates files status and returns automatic violations)
        violations = auditor.run_audit()
        
        # Also fetch all violations (both manual/AI and automatic) from compliance_violations table
        all_violations = repository.compliance.get_violations()
    except Exception as e:
        return f"Error running compliance audit: {e}"
    finally:
        db_conn.close()

    if not all_violations:
        return "## Compliance Audit\n\n**No boundary rule violations found** project-wide."

    md = [f"## Compliance Audit Report: {len(all_violations)} violation(s) found\n"]
    for i, v in enumerate(all_violations, 1):
        origin_str = f" [{v['origin'].upper()}]" if v.get("origin") else ""
        md.append(f"{i}. **[{v['rule_id']}]**{origin_str} (File: `{v['filepath']}:L{v['line']}`)")
        if v['symbol']:
            md.append(f"   - **Symbol**: `{v['symbol']}`")
        md.append(f"   - **Violation**: {v['message']}")
        md.append("")
    return "\n".join(md)


@mcp.tool()
def map() -> str:
    """
    Provides a high-level architectural map of the repository, including total counts,
    automatically detected symbol communities (using Label Propagation), inter-module call weights,
    and the most connected hub symbols in each community.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        totals = repository.metrics.get_repo_totals()
        communities, connections, degrees = detect_communities(repository)
    except Exception as e:
        return f"Error building architectural graph map: {e}"
    finally:
        db_conn.close()

    md = ["## Repository Architectural Blueprint Map\n"]

    md.append("### Project Totals")
    md.append(f"- **Files Indexed**: {totals['files']}")
    md.append(f"- **Symbols Registered**: {totals['symbols']}")
    md.append(f"- **Dependencies (Call Graph Edges)**: {totals['edges']}")
    md.append(f"- **Active Architectural Violations**: {totals['violations']}")
    md.append("")

    md.append("### Detected Architectural Communities")
    if not communities:
        md.append("*No communities detected (empty database).*")
    else:
        sorted_comms = sorted(communities.items(), key=lambda x: len(x[1]), reverse=True)
        for comm_name, syms in sorted_comms:
            md.append(f"#### Community: `{comm_name}` ({len(syms)} symbol(s))")
            comm_syms_sorted = sorted(syms, key=lambda x: degrees.get(x, 0), reverse=True)
            top_hubs = comm_syms_sorted[:3]
            md.append("  - **Key Hub Symbols**:")
            for hub in top_hubs:
                md.append(f"    * `{hub}` (Connections: {degrees.get(hub, 0)})")
            md.append("")

    md.append("### Inter-Community Call Dependencies")
    has_connections = False
    if connections:
        for src_comm, tgts in sorted(connections.items()):
            for tgt_comm, weight in sorted(tgts.items(), key=lambda x: x[1], reverse=True):
                md.append(f"- `{src_comm}` ──[{weight} call(s)]──> `{tgt_comm}`")
                has_connections = True
    if not has_connections:
        md.append("*No inter-community dependencies found.*")
    md.append("")

    return "\n".join(md)


@mcp.tool()
def trace(source: str, sink: str) -> str:
    """
    Traces the data flow path from a source symbol to a sink symbol using CodeQL analysis.
    Returns a Markdown representation of the flow path.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    try:
        from engines.codeql_wrapper import CodeQlWrapper
        codeql = CodeQlWrapper()
    except Exception as e:
        db_conn.close()
        return f"Error importing CodeQL Wrapper: {e}"

    db_dir = ARCH_DIR / "codeql_db"
    if not db_dir.exists():
        db_conn.close()
        return f"Error: CodeQL database not found at {db_dir}. Please create it first."

    try:
        steps = codeql.trace_data_flow(db_dir, source, sink)
    except Exception as e:
        return f"Error running data flow trace: {e}"
    finally:
        db_conn.close()

    if not steps:
        return f"## Data Flow Trace\n\nNo flow path found between source `{source}` and sink `{sink}`."

    md = [f"## Data Flow Trace: Path Found ({len(steps)} steps)\n"]
    for i, step in enumerate(steps, 1):
        md.append(f"{i}. `{step['symbol']}` (`{step['filepath']}:L{step['line']}`)")
    md.append("")

    return "\n".join(md)


@mcp.tool()
def report(name: str, format: str = "markdown") -> str:
    """
    Generates a structured workspace report.
    Parameters:
      name: The name of the report ('overview' or 'compliance').
      format: The output format ('markdown' or 'json', default: 'markdown').
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        from reporter.generator import Reporter
        reporter = Reporter(repository)
        return reporter.generate_report(name, format)
    except Exception as e:
        return f"Error generating report: {e}"
    finally:
        db_conn.close()


@mcp.tool()
def set_fields(
    filepath: Optional[str] = None,
    field: Optional[str] = None,
    value: Optional[Any] = None,
    justification: Optional[str] = None,
    json_filepath: Optional[str] = None
) -> str:
    """
    Updates manual compliance status or manual metadata fields for files.
    Enforces the configuration ontology strictly from config.json.
    
    You must provide EITHER:
      1. 'filepath', 'field', 'value', and 'justification' (optional) to set a single field on a file.
         To set status, use field='status' and value='COMPLIANT' or 'VIOLATION'.
      2. 'json_filepath' pointing to a JSON file containing a mapping of filepaths to fields and values.
         Example: {"lib/widget.dart": {"status": "VIOLATION", "pattern": "Controller"}}
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    # 1. Load config for ontology validation
    config_path = PROJECT_ROOT / ".arch" / "config.json"
    if not config_path.exists():
        db_conn.close()
        return "Error: Ontology config not found at .arch/config.json. Please run 'arch init' first."

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        db_conn.close()
        return f"Error loading config.json: {e}"

    # Helper function to resolve filepath to database matching key
    def resolve_filepath(fp: str) -> Optional[str]:
        file_info = repository.files.get_file(fp)
        if file_info:
            return fp
        all_files = repository.files.get_all_files_metadata()
        for real_fp in all_files.keys():
            if real_fp.replace("\\", "/").endswith(fp.replace("\\", "/")):
                return real_fp
        return None

    # Helper to validate a specific file field updates against the config ontology
    def validate_file_fields(fp: str, fields: dict) -> Optional[str]:
        normalized_path = fp.replace("\\", "/")
        matching_prefix = None
        for prefix in config.keys():
            if prefix == ".":
                if matching_prefix is None:
                    matching_prefix = "."
            elif normalized_path.startswith(prefix):
                if matching_prefix is None or len(prefix) > len(matching_prefix):
                    matching_prefix = prefix
        
        if not matching_prefix:
            return f"No configuration prefix matches file '{fp}'."
            
        prefix_conf = config[matching_prefix]
        manual_cfg = prefix_conf.get("manual_fields", {})
        auto_cfg = prefix_conf.get("automatic_fields", {})

        for f_name, val in fields.items():
            if f_name == "status":
                if str(val).upper() not in ("COMPLIANT", "VIOLATION"):
                    return f"Invalid value '{val}' for field 'status'. Allowed values: 'COMPLIANT', 'VIOLATION'."
                continue

            if f_name in auto_cfg:
                return f"Field '{f_name}' in '{fp}' is an automatic field defined in the ontology and cannot be modified manually."

            if f_name not in manual_cfg:
                return f"Field '{f_name}' is not defined as a manual field in the ontology for prefix '{matching_prefix}'."

            field_conf = manual_cfg[f_name]
            allowed_values = field_conf.get("values")
            if allowed_values is not None:
                if val not in allowed_values:
                    return f"Invalid value '{val}' for manual field '{f_name}' in '{fp}'. Allowed values: {allowed_values}."
            else:
                if not isinstance(val, str):
                    return f"Value for manual field '{f_name}' in '{fp}' must be a string."
        return None

    # Helper to apply the updates to database
    def apply_updates(fp: str, fields: dict):
        status_val = fields.get("status")
        manual_updates = {k: v for k, v in fields.items() if k != "status"}

        if status_val is not None:
            status_db = "VIOLATION_DETECTED" if status_val.upper() == "VIOLATION" else "COMPLIANT"
            repository.files.update_file_manual_status(fp, status_db, justification)
            
            repository.compliance.delete_manual_violations(fp)
            if status_db == "VIOLATION_DETECTED":
                import hashlib
                violation_text = f"manual_logical_audit_{fp}_{justification or ''}"
                violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                repository.compliance.add_violation(
                    violation_id=violation_id,
                    rule_id="logical_audit",
                    symbol=None,
                    filepath=fp,
                    line=1,
                    message=justification or "Manual compliance violation flagged",
                    origin="manual"
                )

        if manual_updates:
            file_info = repository.files.get_file(fp)
            current_fields = {}
            if file_info and file_info.get("manual_fields"):
                try:
                    current_fields = json.loads(file_info["manual_fields"])
                except Exception:
                    pass
            for k, v in manual_updates.items():
                if v is None:
                    current_fields.pop(k, None)
                else:
                    current_fields[k] = v
            repository.files.update_file_manual_fields(fp, current_fields, justification)

    try:
        updates_map = {}
        if json_filepath:
            path_obj = Path(json_filepath)
            if not path_obj.is_absolute():
                path_obj = PROJECT_ROOT / path_obj
            if not path_obj.exists():
                return f"Error: JSON file not found at {path_obj}"
            with open(path_obj, "r", encoding="utf-8") as f:
                raw_json = json.load(f)
            if not isinstance(raw_json, dict):
                return "Error: JSON file must contain a top-level object mapping filepaths to fields."
            updates_map = raw_json
        else:
            if not filepath or not field:
                return "Error: You must provide either 'json_filepath' or both 'filepath' and 'field'."
            updates_map = {filepath: {field: value}}

        # Resolve paths and validate first (atomic validations)
        resolved_updates = {}
        for raw_fp, fields in updates_map.items():
            real_fp = resolve_filepath(raw_fp)
            if not real_fp:
                return f"Error: File '{raw_fp}' is not registered in the database. Please index it first."
            
            val_err = validate_file_fields(real_fp, fields)
            if val_err:
                return f"Ontology Validation Error: {val_err}"
            
            resolved_updates[real_fp] = fields

        # Apply updates
        for real_fp, fields in resolved_updates.items():
            apply_updates(real_fp, fields)

        # Run compliance audit to propagate changes
        auditor = Auditor(repository, PROJECT_ROOT)
        auditor.run_audit()

        return f"Successfully updated manual fields and compliance status for {len(resolved_updates)} file(s) and re-ran audit."
    except Exception as e:
        return f"Error updating fields: {e}"
    finally:
        db_conn.close()


@mcp.tool()
def clear_pending_audits() -> str:
    """
    Clears the pending audit flags for all files in the database.
    Use this after large refactors or git checkout operations when you know the changes are compliant.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        repository.files.clear_all_pending_audits("Cleared manually via API")
        # Run audit to clean up all pending_audit violations
        auditor = Auditor(repository, PROJECT_ROOT)
        auditor.run_audit()
        return "Successfully cleared pending audit status for all files."
    except Exception as e:
        return f"Error clearing pending audits: {e}"
    finally:
        db_conn.close()


@mcp.tool()
def index(table: str, key: Optional[str] = None, limit: int = 50) -> str:
    """
    Retrieves metadata, properties, and relationships from the database index tables.
    Supported tables:
      - 'files': Lists/details files in the project index. key = filepath or suffix.
      - 'symbols' (or 'nodes'): Lists/details code symbols. key = symbol name.
      - 'occurrences': Lists coordinates/line numbers of symbol definitions/references. key = symbol name.
      - 'edges': Lists call-graph dependencies. key = symbol name (matches either caller/source or callee/target).
      - 'violations': Lists architectural compliance violations. key = filepath or rule_id.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    
    table_lower = table.lower().strip()
    if table_lower in ("nodes", "node"):
        table_name = "symbols"
    elif table_lower in ("violations", "violation"):
        table_name = "compliance_violations"
    elif table_lower in ("edges", "edge", "dependencies", "dependency"):
        table_name = "edges"
    elif table_lower in ("occurrences", "occurrence"):
        table_name = "occurrences"
    elif table_lower in ("files", "file"):
        table_name = "files"
    else:
        db_conn.close()
        return f"Error: Unsupported table '{table}'. Supported tables: files, symbols (nodes), occurrences, edges, violations."

    md = [f"## Database Index: `{table_name}`\n"]

    try:
        with db_conn.session() as conn:
            if not key:
                # Listing mode
                if table_name == "files":
                    rows = conn.execute(
                        "SELECT filepath, language, status, manual_status, pending_audit FROM files LIMIT ?",
                        (limit,)
                    ).fetchall()
                    md.append("| Filepath | Language | Status | Manual Status | Pending Audit |")
                    md.append("| :--- | :--- | :--- | :--- | :--- |")
                    for r in rows:
                        md.append(f"| `{r[0]}` | `{r[1]}` | `{r[2]}` | `{r[3]}` | `{r[4]}` |")

                elif table_name == "symbols":
                    rows = conn.execute(
                        "SELECT symbol, filepath, kind, signature, docstring FROM symbols LIMIT ?",
                        (limit,)
                    ).fetchall()
                    md.append("| Symbol | Filepath | Kind | Signature | Docstring |")
                    md.append("| :--- | :--- | :--- | :--- | :--- |")
                    for r in rows:
                        doc = r[4].strip().split("\n")[0] if r[4] else ""
                        md.append(f"| `{r[0]}` | `{r[1] or ''}` | `{r[2]}` | `{r[3] or ''}` | {doc} |")

                elif table_name == "occurrences":
                    rows = conn.execute(
                        "SELECT symbol, filepath, start_line, end_line, role FROM occurrences LIMIT ?",
                        (limit,)
                    ).fetchall()
                    md.append("| Symbol | Filepath | Line Range | Role |")
                    md.append("| :--- | :--- | :--- | :--- |")
                    for r in rows:
                        md.append(f"| `{r[0]}` | `{r[1]}` | L{r[2]}-{r[3]} | {r[4]} |")

                elif table_name == "edges":
                    rows = conn.execute(
                        "SELECT source, target, relation FROM edges LIMIT ?",
                        (limit,)
                    ).fetchall()
                    md.append("| Source (Caller) | Target (Callee) | Relation |")
                    md.append("| :--- | :--- | :--- |")
                    for r in rows:
                        md.append(f"| `{r[0]}` | `{r[1]}` | `{r[2]}` |")

                elif table_name == "compliance_violations":
                    rows = conn.execute(
                        "SELECT violation_id, rule_id, symbol, filepath, line, message, origin FROM compliance_violations LIMIT ?",
                        (limit,)
                    ).fetchall()
                    md.append("| Violation ID | Rule ID | Symbol | Filepath:Line | Message | Origin |")
                    md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
                    for r in rows:
                        md.append(f"| `{r[0]}` | `{r[1]}` | `{r[2] or ''}` | `{r[3]}:{r[4]}` | {r[5]} | `{r[6]}` |")

                md.append(f"\n*Showing up to {limit} rows (no key specified).*")

            else:
                # Key details mode
                key_wildcard = f"%{key}%"
                if table_name == "files":
                    rows = conn.execute(
                        """
                        SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification 
                        FROM files 
                        WHERE filepath = ? OR filepath LIKE ?
                        """,
                        (key, f"%{key.replace('\\', '/')}%")
                    ).fetchall()
                    if not rows:
                        md.append(f"*No matching files found for key '{key}'.*")
                    for r in rows:
                        md.append(f"### File: `{r[0]}`")
                        md.append(f"- **Language**: `{r[2]}`")
                        md.append(f"- **SHA-256 Hash**: `{r[1]}`")
                        md.append(f"- **Last Indexed**: `{r[3]}`")
                        md.append(f"- **Computed Status**: `{r[4]}`")
                        md.append(f"- **Manual Status**: `{r[5]}`")
                        md.append(f"- **Pending Audit**: `{r[6]}`")
                        md.append(f"- **Justification Comment**: *{r[8] or 'None'}*")
                        md.append(f"- **Manual Fields**: `{r[7]}`")
                        md.append("")

                elif table_name == "symbols":
                    rows = conn.execute(
                        """
                        SELECT symbol, filepath, kind, signature, docstring, body_hash 
                        FROM symbols 
                        WHERE symbol = ? OR symbol LIKE ?
                        """,
                        (key, key_wildcard)
                    ).fetchall()
                    if not rows:
                        md.append(f"*No matching symbols found for key '{key}'.*")
                    for r in rows:
                        md.append(f"### Symbol: `{r[0]}`")
                        md.append(f"- **Filepath**: `{r[1] or 'External'}`")
                        md.append(f"- **Kind**: `{r[2]}`")
                        md.append(f"- **Signature**: `{r[3] or 'None'}`")
                        md.append(f"- **Body AST Hash**: `{r[5] or 'None'}`")
                        doc = r[4].strip() if r[4] else "None"
                        md.append(f"- **Docstring**:\n  {doc.replace('\n', '\n  ')}")
                        md.append("")

                elif table_name == "occurrences":
                    rows = conn.execute(
                        """
                        SELECT symbol, filepath, start_line, start_col, end_line, end_col, role 
                        FROM occurrences 
                        WHERE symbol = ? OR symbol LIKE ?
                        """,
                        (key, key_wildcard)
                    ).fetchall()
                    if not rows:
                        md.append(f"*No matching occurrences found for key '{key}'.*")
                    else:
                        md.append("| Symbol | Filepath | Line Range | Cols | Role |")
                        md.append("| :--- | :--- | :--- | :--- | :--- |")
                        for r in rows:
                            md.append(f"| `{r[0]}` | `{r[1]}` | L{r[2]}-{r[4]} | C{r[3]}-{r[5]} | {r[6]} |")

                elif table_name == "edges":
                    rows = conn.execute(
                        """
                        SELECT source, target, relation 
                        FROM edges 
                        WHERE source = ? OR target = ? OR source LIKE ? OR target LIKE ?
                        """,
                        (key, key, key_wildcard, key_wildcard)
                    ).fetchall()
                    if not rows:
                        md.append(f"*No matching edges found for key '{key}'.*")
                    else:
                        md.append("| Source (Caller) | Target (Callee) | Relation |")
                        md.append("| :--- | :--- | :--- |")
                        for r in rows:
                            md.append(f"| `{r[0]}` | `{r[1]}` | `{r[2]}` |")

                elif table_name == "compliance_violations":
                    rows = conn.execute(
                        """
                        SELECT violation_id, rule_id, symbol, filepath, line, message, checked_at, origin 
                        FROM compliance_violations 
                        WHERE filepath LIKE ? OR rule_id = ? OR symbol = ?
                        """,
                        (f"%{key}%", key, key)
                    ).fetchall()
                    if not rows:
                        md.append(f"*No matching compliance violations found for key '{key}'.*")
                    else:
                        md.append("| Violation ID | Rule ID | Symbol | Filepath:Line | Message | Checked At | Origin |")
                        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                        for r in rows:
                            md.append(f"| `{r[0]}` | `{r[1]}` | `{r[2] or ''}` | `{r[3]}:{r[4]}` | {r[5]} | `{r[6]}` | `{r[7]}` |")
    except Exception as e:
        return f"Error executing index query: {e}"
    finally:
        db_conn.close()

    return "\n".join(md)


@mcp.tool()
def compile_context(
    symbol: str,
    radius: int = 2,
    direction: str = "downstream",
    resolution: str = "full",
    out_filepath: Optional[str] = None
) -> str:
    """
    Compiles a deterministic markdown-formatted architectural context document
    starting from a focal symbol, traversing its call graph neighborhood.
    Use this to see caller/callee implementations and metadata.
    
    Parameters:
      symbol: The name of the focal symbol to start compilation from.
      radius: Traversal depth / number of hops along the call graph (default: 2).
      direction: Traversal direction: 'downstream' (callees), 'upstream' (callers), or 'both' (default: 'downstream').
      resolution: Neighbors detail level: 'full' (include complete code bodies) or 'signature' (signatures & docstrings only) (default: 'full').
      out_filepath: Optional path (relative to project root) to write the compiled context markdown to.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    direction = direction.lower()
    if direction not in ("upstream", "downstream", "both"):
        return f"Error: Invalid direction: '{direction}'. Allowed: upstream, downstream, both."

    resolution = resolution.lower()
    if resolution not in ("full", "signature"):
        return f"Error: Invalid resolution: '{resolution}'. Allowed: full, signature."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)
    compiler = ContextCompiler(repository, PROJECT_ROOT)

    try:
        return compiler.compile(
            focal_symbol=symbol,
            radius=radius,
            direction=direction,
            resolution=resolution,
            out_filepath=out_filepath
        )
    except Exception as e:
        return f"Error compiling architectural context: {e}"
    finally:
        db_conn.close()


if __name__ == "__main__":
    # Start the FastMCP server (standard stdin/stdout communication)
    mcp.run()
