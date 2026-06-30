import os
import sys
import json
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
from auditor.compiler import ContextCompiler
from auditor.validator import ConfigValidator
from engines.embedder import LocalEmbedder
from engines.communities import detect_communities

# Resolve project root: explicit arg > env var > CWD
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    PROJECT_ROOT = Path(sys.argv[1]).resolve()
elif os.environ.get("ARCH_PROJECT_ROOT"):
    PROJECT_ROOT = Path(os.environ["ARCH_PROJECT_ROOT"]).resolve()
else:
    PROJECT_ROOT = Path.cwd().resolve()

ARCH_DIR = PROJECT_ROOT / ".arch"
DB_PATH = ARCH_DIR / "arch.db"

def get_bin_dir() -> Path:
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "bin").exists():
            return exe_dir / "bin"
        return exe_dir.parent / "bin"
    return src_dir.parent / "bin"

# Initialize FastMCP Server
mcp = FastMCP("arch")


@mcp.tool()
def query(text: Union[List[str], str], limit: int = 5) -> str:
    """
    Runs keyword and semantic searches over symbols, docstrings, and files in the codebase.
    Accepts a single query string or a list of query strings, returning matches for each.
    
    Best Practice: Use multiple, focused search terms (e.g. as a list of strings) instead
    of a single string combined with logical operators like "and" or "or". Use this tool to
    discover target symbols or files before reading them.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    # Force queries into a list
    queries = [text] if isinstance(text, str) else text

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)
    embedder = None

    try:
        bin_dir = get_bin_dir()
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
    
    Guidelines:
      - Always call this tool before reading the contents of a file to locate definitions
        and identify line ranges to check, especially for large files.
      - Pass multiple file paths to this tool when scanning or locating paths that implement
        a specific interface or package feature.
        
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
    
    Guidelines:
      - Use when editing critical/central code, or before modifying interfaces/signatures
        that control many downstream targets, to understand what components the change
        might impact and prevent regressions.
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
    Runs the project-wide architectural boundary rules compliance audit based on Layer/Tier rules in config.json.
    
    Guidelines:
      - This tool operates on the architectural rules database. Run this tool only when explicitly
        prompted/instructed by the user or other skills.
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
    
    Guidelines:
      - Use map at the start of a task when no information for the project is available.
        It gives a bird's-eye view of the project and module dependencies.
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
    Traces the data flow path from a source symbol to a sink symbol.
    Combines Dart analyzer + CodeQL + FFI_Binds for cross-language tracing.
    Returns a Markdown representation of the flow path.

    Guidelines:
      - This tool is especially useful when fixing bugs. Use it to trace data flows and understand
        exactly where to place debugging print/log statements or checks.
      - Supports cross-language traces: any language -> FFI -> any other language
      - Auto-detects languages from symbol names or file paths
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)
    repository = Repository(db_conn)

    try:
        from engines.dart_analyzer import CombinedDataflowTracer, DartAnalyzerDB
        from engines.codeql_wrapper import CodeQlWrapper

        # Initialize analyzer DB if it exists (for Dart)
        analyzer_db = None
        dart_db_path = ARCH_DIR / "dart_analyzer_db"
        if dart_db_path.exists():
            analyzer_db = DartAnalyzerDB(ARCH_DIR)

        # Initialize CodeQL wrappers for each available language database
        codeql_wrappers = {}
        try:
            bin_dir = get_bin_dir()
            # Check for language-specific and generic CodeQL databases
            for db_entry in ARCH_DIR.iterdir():
                if db_entry.is_dir() and db_entry.name.startswith("codeql_db"):
                    # Extract language from dir name (e.g., "codeql_db_rust" -> "rust")
                    lang = db_entry.name.replace("codeql_db_", "").replace("codeql_db", "")
                    if not lang:
                        lang = "generic"
                    try:
                        codeql = CodeQlWrapper(bin_dir)
                        if codeql.is_available():
                            codeql_wrappers[lang] = codeql
                    except Exception:
                        pass
        except Exception:
            pass

        # Use combined tracer (language-agnostic: analyzer + CodeQL + FFI_Binds)
        tracer = CombinedDataflowTracer(
            project_root=ARCH_DIR.parent,
            arch_dir=ARCH_DIR,
            analyzer_db=analyzer_db,
            codeql_wrappers=codeql_wrappers,
            repository=repository
        )
        steps = tracer.trace(source, sink)

    except Exception as e:
        return f"Error running data flow trace: {e}"
    finally:
        db_conn.close()

    if not steps:
        return f"## Data Flow Trace\n\nNo flow path found between source `{source}` and sink `{sink}`."

    md = [f"## Data Flow Trace: Path Found ({len(steps)} steps)\n"]
    for i, step in enumerate(steps, 1):
        lang_tag = f" [{step.language}]" if step.language and step.language != "unknown" else ""
        md.append(f"{i}. `{step.symbol}` (`{step.filepath}:L{step.line}`){lang_tag}")
    md.append("")

    return "\n".join(md)


@mcp.tool()
def report(name: str, format: str = "markdown") -> str:
    """
    Generates a structured workspace report.
    Parameters:
      name: The name of the report ('overview' or 'compliance').
      format: The output format ('markdown' or 'json', default: 'markdown').
      
    Guidelines:
      - Similar to compile_context, but provides less direct control and a broader view of
        the workspace across different aspects.
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
    target: str,
    update: Optional[str] = None,
    justification: Optional[str] = None
) -> str:
    """
    Updates manual compliance status or manual metadata fields for files.
    Enforces the configuration ontology strictly from config.json.
    
    Parameters:
      target: Either a JSON filepath (for batch updates) or a source filepath.
      update: Optional. Combined field and value string in the format "field:value".
              Example: "status:VIOLATION" or "pattern:Controller".
      justification: Optional. Explanatory comment for the status update (required if status is VIOLATION).
      
    Guidelines:
      - This tool operates on config.json compliance flags and statuses. Run this tool only
        when instructed by the user's prompt or other skills on how and where to use it.
      - Negative Constraint: Do NOT modify the ontology config.json file directly without
        first consulting the user.
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
        if update is None:
            # Batch update from JSON file
            path_obj = Path(target)
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
            # Single field update
            if ":" not in update:
                return "Error: Update parameter must be in the format 'field:value'."
            field, val = update.split(":", 1)
            field = field.strip()
            val = val.strip()
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.lower() == "null":
                val = None
            
            updates_map = {target: {field: val}}

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
    
    Guidelines:
      - This tool operates on the database's compliance state. Run this tool only when instructed
        by the user's prompt or other skills on how and where to use it.
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
def index(target: str) -> str:
    """
    Looks up details, metadata, and relationships for a file module or code symbol.
    The tool automatically detects whether the target is a file path (e.g. 'auditor.analyzer' 
    or 'src/auditor/analyzer.py') or a code symbol (e.g. 'auditor.analyzer.Auditor.run_audit').
    
    Guidelines:
      - Use to retrieve symbol definitions, occurrences, and relationships for any target symbol
        or file module before reading or modifying it.
    """
    if not DB_PATH.exists():
        return f"Error: Arch database not found at {DB_PATH}. Please run 'arch init' first."

    db_conn = DbConnection(DB_PATH)

    # Normalize target for file matching (replace dots with slashes)
    target_normalized = target.strip()
    target_slashes = target_normalized.replace(".", "/")

    exact_symbol = None
    matching_symbols = []
    exact_file = None
    matching_files = []

    try:
        with db_conn.session() as conn:
            # A. Search symbols table
            sym_row = conn.execute(
                "SELECT symbol, filepath, kind, signature, docstring, body_hash FROM symbols WHERE symbol = ?",
                (target_normalized,)
            ).fetchone()
            if sym_row:
                exact_symbol = sym_row
            else:
                # Substring search
                sym_rows = conn.execute(
                    "SELECT symbol, filepath, kind, signature, docstring FROM symbols WHERE symbol LIKE ? LIMIT 10",
                    (f"%{target_normalized}%",)
                ).fetchall()
                matching_symbols = sym_rows

            # B. Search files table
            file_row = conn.execute(
                """
                SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification 
                FROM files 
                WHERE filepath = ? OR replace(filepath, '\\', '/') = ?
                """,
                (target_normalized, target_normalized.replace("\\", "/"))
            ).fetchone()
            
            if file_row:
                exact_file = file_row
            else:
                file_rows = conn.execute(
                    """
                    SELECT filepath, sha256, language, last_indexed, status, manual_status, pending_audit, manual_fields, justification 
                    FROM files 
                    WHERE replace(filepath, '\\', '/') LIKE ? OR replace(filepath, '\\', '/') = ?
                    """,
                    (f"%{target_slashes}%", target_slashes)
                ).fetchall()
                if file_rows:
                    if len(file_rows) == 1:
                        exact_file = file_rows[0]
                    else:
                        matching_files = file_rows

        # Generate markdown output
        md = []
        
        # 1. Exact Symbol Details
        if exact_symbol:
            md.append(f"## Code Symbol: `{exact_symbol[0]}`\n")
            md.append(f"- **Filepath**: `{exact_symbol[1] or 'External / Third-party'}`")
            md.append(f"- **Kind**: `{exact_symbol[2]}`")
            md.append(f"- **Signature**: `{exact_symbol[3] or 'None'}`")
            doc = exact_symbol[4].strip() if exact_symbol[4] else "No docstring available."
            md.append(f"- **Docstring**:\n  {doc.replace('\n', '\n  ')}\n")

            with db_conn.session() as conn:
                occs = conn.execute(
                    "SELECT filepath, start_line, end_line, role FROM occurrences WHERE symbol = ?",
                    (exact_symbol[0],)
                ).fetchall()
                edges = conn.execute(
                    "SELECT source, target, relation FROM edges WHERE source = ? OR target = ?",
                    (exact_symbol[0], exact_symbol[0])
                ).fetchall()

            if occs:
                md.append("### Symbol Occurrences")
                md.append("| Filepath | Line Range | Role (Definition=1, Ref=2) |")
                md.append("| :--- | :--- | :--- |")
                for o in occs:
                    md.append(f"| `{o[0]}` | L{o[1]}-{o[2]} | {o[3]} |")
                md.append("")

            if edges:
                md.append("### Call Graph Relationships")
                md.append("| Source (Caller) | Target (Callee) | Relation |")
                md.append("| :--- | :--- | :--- |")
                for e in edges:
                    md.append(f"| `{e[0]}` | `{e[1]}` | `{e[2]}` |")
                md.append("")

        # 2. Exact File Details
        if exact_file:
            md.append(f"## File Module: `{exact_file[0]}`\n")
            md.append(f"- **Language**: `{exact_file[2]}`")
            md.append(f"- **Computed Status**: `{exact_file[4]}`")
            md.append(f"- **Manual status**: `{exact_file[5]}`")
            md.append(f"- **Pending Audit**: `{exact_file[6]}`")
            md.append(f"- **Justification**: *{exact_file[8] or 'None'}*")
            md.append(f"- **Manual Fields**: `{exact_file[7]}`\n")

            with db_conn.session() as conn:
                file_syms = conn.execute(
                    "SELECT symbol, kind, signature FROM symbols WHERE filepath = ?",
                    (exact_file[0],)
                ).fetchall()
            
            if file_syms:
                md.append("### Symbols Declared in File")
                md.append("| Symbol | Kind | Signature |")
                md.append("| :--- | :--- | :--- |")
                for s in file_syms:
                    md.append(f"| `{s[0]}` | `{s[1]}` | `{s[2] or ''}` |")
                md.append("")

        # 3. Substring listing
        if not exact_symbol and not exact_file:
            if matching_files:
                md.append("### Matching File Modules Found")
                for f in matching_files:
                    md.append(f"- **{f[0]}** (Language: `{f[2]}`, Status: `{f[4]}`)")
                md.append("")

            if matching_symbols:
                md.append("### Matching Code Symbols Found")
                for s in matching_symbols:
                    md.append(f"- **{s[0]}** (`{s[2]}` in `{s[1] or 'External'}`)")
                md.append("")

            if not matching_files and not matching_symbols:
                md.append(f"*No files or symbols matched target query: '{target}'*")

        db_conn.close()
        return "\n".join(md)
    except Exception as e:
        db_conn.close()
        return f"Error executing index search: {e}"


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
      
    Guidelines:
      - Use in different kinds of scenarios, such as when you want to explain code logic,
        generate a recap, or compile comprehensive context for code modifications.
      - Negative Constraint: Do NOT run this tool with a radius > 2 or resolution='full' unless
        necessary, as it rapidly consumes the token context window budget.
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


@mcp.tool()
def analyze() -> str:
    """
    Validates the architectural configuration ontology (config.json) completeness and sanity.
    Checks syntax, structure, allowed values reachability, dependency rules referential integrity,
    and propagation barriers validation. Returns a Markdown report summarizing issues.
    
    Guidelines:
      - Use this tool ONLY after modifying the ontology configuration file (config.json) to
        validate its completeness and sanity.
    """
    validator = ConfigValidator(PROJECT_ROOT)
    res = validator.validate()

    md = ["# Configuration Ontology Validation Report\n"]

    if res["success"]:
        md.append("✅ **Ontology validation passed successfully.**\n")
    else:
        md.append("❌ **Ontology validation failed with errors.**\n")

    if res["warnings"]:
        md.append("### Warnings")
        for warning in res["warnings"]:
            md.append(f"- ⚠️ {warning}")
        md.append("")

    if res["errors"]:
        md.append("### Errors")
        for error in res["errors"]:
            md.append(f"- 🛑 {error}")
        md.append("")
    else:
        md.append("✅ Referential integrity validation passed.\n")

    return "\n".join(md)


def _filter_blank_stdin() -> None:
    """Filter blank lines from stdin before MCP reads it.

    Some MCP clients (Claude Desktop, etc.) send blank lines between JSON
    messages. The MCP stdio transport tries to parse every line as a
    JSONRPCMessage, so a bare newline triggers a Pydantic ValidationError.
    This installs an OS-level pipe that relays stdin while dropping blanks.
    """
    import os
    import threading

    try:
        r_fd, w_fd = os.pipe()
        saved_fd = os.dup(sys.stdin.fileno())

        def _relay() -> None:
            try:
                with open(saved_fd, "rb") as src, open(w_fd, "wb") as dst:
                    for line in src:
                        if line.strip():
                            dst.write(line)
                            dst.flush()
            except Exception:
                pass

        threading.Thread(target=_relay, daemon=True).start()
        os.dup2(r_fd, sys.stdin.fileno())
        os.close(r_fd)
        sys.stdin = open(0, "r", closefd=False)
    except Exception:
        pass


def run_server():
    # Filter blank stdin lines to prevent FastMCP crashes
    _filter_blank_stdin()
    # Start the FastMCP server (standard stdin/stdout communication)
    mcp.run()


if __name__ == "__main__":
    run_server()
