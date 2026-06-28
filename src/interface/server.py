import os
import sys
from pathlib import Path
from typing import Optional, Union, List

# Setup sys.path to resolve imports from src/
src_dir = Path(__file__).resolve().parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from mcp.server.fastmcp import FastMCP
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor
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
    Runs a semantic search over the docstrings of indexed symbols in the codebase.
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
            embedding = embedder.embed(q)
            results = repository.symbols.semantic_search(embedding, limit=limit)
            
            md.append(f"## Semantic Search Results for: \"{q}\"\n")
            if not results:
                md.append("*No matching symbols found.*\n")
                continue
                
            for i, res in enumerate(results, 1):
                md.append(f"{i}. **{res['symbol']}** (Similarity: {res['similarity']:.2f})")
                md.append(f"   - **File**: `{res['filepath']}`")
                md.append(f"   - **Kind**: `{res['kind']}`")
                if res['signature']:
                    md.append(f"   - **Signature**: `{res['signature']}`")
                if res['docstring']:
                    doc = res['docstring'].strip().replace("\n", "\n     ")
                    md.append(f"   - **Doc**: {doc}")
                md.append("")
    except Exception as e:
        return f"Error executing semantic search: {e}"
    finally:
        db_conn.close()

    return "\n".join(md)


@mcp.tool()
def context(filepath: str) -> str:
    """
    Provides a compact structural index (Table of Contents) of all classes, methods,
    and functions declared in the specified file, along with their precise line ranges.
    Use this to locate specific definitions before reading the code.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        symbols = repository.symbols.get_symbols_in_file(filepath)
        # Fetch all occurrences in this file to match start/end line coordinates in a single session
        with db_conn.session() as conn:
            occs = conn.execute(
                """
                SELECT symbol, start_line, end_line, role 
                FROM occurrences 
                WHERE replace(filepath, '\\', '/') = ? OR filepath = ?
                """,
                (filepath.replace("\\", "/"), filepath)
            ).fetchall()
    except Exception as e:
        return f"Error retrieving context for file {filepath}: {e}"
    finally:
        db_conn.close()

    if not symbols:
        return f"No indexed symbols found in file: `{filepath}`. Make sure the file has been indexed."

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

    md = [f"## File Index: `{filepath}`\n"]

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

    return "\n".join(md)


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
def audit(filepath: Optional[str] = None) -> str:
    """
    Runs the architectural boundary rules compliance audit.
    If filepath is provided, restricts checks to code calling from that file/prefix.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)
    auditor = Auditor(repository, PROJECT_ROOT)

    try:
        # Run static compliance check (updates files status and returns automatic violations)
        violations = auditor.run_audit(filepath_filter=filepath)
        
        # Also fetch all violations (both manual/AI and automatic) from compliance_violations table
        all_violations = repository.compliance.get_violations()
        if filepath:
            normalized_filter = filepath.replace("\\", "/")
            all_violations = [v for v in all_violations if v["filepath"].replace("\\", "/").startswith(normalized_filter)]
    except Exception as e:
        return f"Error running compliance audit: {e}"
    finally:
        db_conn.close()

    if not all_violations:
        scope = f"for `{filepath}`" if filepath else "project-wide"
        return f"## Compliance Audit\n\n**No boundary rule violations found** {scope}."

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
def set_file_status(filepath: str, status: str, justification: Optional[str] = None) -> str:
    """
    Sets the manual compliance status flag (logical audit) for a file component.
    Parameters:
      filepath: Path to the target file.
      status: Compliance status ('COMPLIANT' or 'VIOLATION_DETECTED').
      justification: Explanatory comment for the status (required if status is 'VIOLATION_DETECTED').
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    status = status.upper()
    if status not in ("COMPLIANT", "VIOLATION_DETECTED"):
        return f"Error: Invalid compliance status choice: {status}. Allowed values: COMPLIANT, VIOLATION_DETECTED."

    if status == "VIOLATION_DETECTED" and not justification:
        return "Error: Justification must be provided when flagging a file as VIOLATION_DETECTED."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        # Check if the file is registered in the database
        file_info = repository.files.get_file(filepath)
        if not file_info:
            all_files = repository.files.get_all_files_metadata()
            matched = None
            for fp in all_files.keys():
                if fp.replace("\\", "/").endswith(filepath.replace("\\", "/")):
                    matched = fp
                    break
            if matched:
                filepath = matched
            else:
                return f"Error: File '{filepath}' is not registered in the database. Please index it first."

        # 1. Update manual_status and justification in files table
        repository.files.update_file_manual_status(filepath, status, justification)
        
        # 2. Sync manual violations in compliance_violations table
        # Clear existing manual violations for this file
        repository.compliance.delete_manual_violations(filepath)
        
        # If the manual status is VIOLATION_DETECTED, insert a manual violation
        if status == "VIOLATION_DETECTED":
            import hashlib
            violation_text = f"manual_logical_audit_{filepath}_{justification}"
            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
            
            repository.compliance.add_violation(
                violation_id=violation_id,
                rule_id="logical_audit",
                symbol=None,
                filepath=filepath,
                line=1,
                message=justification,
                origin="manual"
            )

        return f"Successfully updated manual status for '{filepath}' to '{status}'."
    except Exception as e:
        return f"Error setting file status: {e}"
    finally:
        db_conn.close()


@mcp.tool()
def set_file_fields(filepath: str, fields: dict, justification: Optional[str] = None) -> str:
    """
    Attaches arbitrary manual metadata fields to a file component.
    Parameters:
      filepath: Path to the target file.
      fields: Dict containing metadata key-value annotations (e.g. {"pattern": "Controller"}).
      justification: Optional explanation of the metadata update.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        file_info = repository.files.get_file(filepath)
        if not file_info:
            # Try resolving path
            all_files = repository.files.get_all_files_metadata()
            matched = None
            for fp in all_files.keys():
                if fp.replace("\\", "/").endswith(filepath.replace("\\", "/")):
                    matched = fp
                    break
            if matched:
                filepath = matched
            else:
                return f"Error: File '{filepath}' is not registered in the database. Please index it first."

        # Fetch current manual fields to merge updates
        current_fields = {}
        if file_info.get("manual_fields"):
            import json
            try:
                current_fields = json.loads(file_info["manual_fields"])
            except Exception:
                pass
        
        # Update/Merge fields
        for k, v in fields.items():
            if v is None:
                current_fields.pop(k, None)
            else:
                current_fields[k] = v

        repository.files.update_file_manual_fields(filepath, current_fields, justification)
        
        # Run audit to propagate metadata changes
        auditor = Auditor(repository, PROJECT_ROOT)
        auditor.run_audit()
        
        return f"Successfully updated manual fields for '{filepath}' to: {current_fields}."
    except Exception as e:
        return f"Error setting file fields: {e}"
    finally:
        db_conn.close()


@mcp.tool()
def clear_pending_audits(justification: str) -> str:
    """
    Clears the pending audit flags for all files in the database.
    Use this after large refactors or git checkout operations when you know the changes are compliant.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        repository.files.clear_all_pending_audits(justification)
        # Run audit to clean up all pending_audit violations
        auditor = Auditor(repository, PROJECT_ROOT)
        auditor.run_audit()
        return "Successfully cleared pending audit status for all files."
    except Exception as e:
        return f"Error clearing pending audits: {e}"
    finally:
        db_conn.close()


@mcp.tool()
def get_file_details(filepath: str) -> str:
    """
    Retrieves full indexing, compliance status, manual status, and metadata fields for a specific file.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        file_info = repository.files.get_file(filepath)
        if not file_info:
            all_files = repository.files.get_all_files_metadata()
            matched = None
            for fp in all_files.keys():
                if fp.replace("\\", "/").endswith(filepath.replace("\\", "/")):
                    matched = fp
                    break
            if matched:
                filepath = matched
                file_info = repository.files.get_file(filepath)
            
        if not file_info:
            return f"Error: File '{filepath}' is not registered in the database."

        import json
        m_fields = {}
        if file_info.get("manual_fields"):
            try:
                m_fields = json.loads(file_info["manual_fields"])
            except Exception:
                pass

        md = [
            f"## File Details: `{file_info['filepath']}`\n",
            f"- **Language**: `{file_info['language']}`",
            f"- **SHA-256 Hash**: `{file_info['sha256']}`",
            f"- **Last Indexed**: `{file_info['last_indexed']}`",
            f"- **Automatically Computed Status**: `{file_info['status']}`",
            f"- **Manual AI Audit Status**: `{file_info['manual_status']}`",
            f"- **Pending Audit**: `{file_info['pending_audit']}`",
            f"- **Justification Comment**: *{file_info['justification'] or 'None'}*",
            f"- **Manual Fields/Annotations**: `{m_fields}`"
        ]
        return "\n".join(md)
    except Exception as e:
        return f"Error retrieving file details: {e}"
    finally:
        db_conn.close()


if __name__ == "__main__":
    # Start the FastMCP server (standard stdin/stdout communication)
    mcp.run()
