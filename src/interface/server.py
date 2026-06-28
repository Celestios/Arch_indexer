import os
import sys
import random
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

# Resolve the target project root (where the .arch/ database resides)
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    PROJECT_ROOT = Path(sys.argv[1]).resolve()
else:
    PROJECT_ROOT = Path(os.environ.get("ARCH_PROJECT_ROOT", os.getcwd())).resolve()

ARCH_DIR = PROJECT_ROOT / ".arch"
DB_PATH = ARCH_DIR / "arch.db"

# Initialize FastMCP Server
mcp = FastMCP("arch")


def detect_communities(repository: Repository):
    """
    Groups repository symbols into cohesive communities using Label Propagation (LPA).
    """
    # Fetch symbols and edges
    with repository.db_conn.session() as conn:
        symbols_res = conn.execute("SELECT symbol, filepath FROM symbols").fetchall()
        edges_res = conn.execute("SELECT source, target FROM edges").fetchall()

    symbols = {r[0]: r[1] for r in symbols_res}
    edges = [(r[0], r[1]) for r in edges_res]

    # Build adjacency list (undirected for community propagation)
    adj = {sym: set() for sym in symbols}
    for src, tgt in edges:
        if src in adj and tgt in adj:
            adj[src].add(tgt)
            adj[tgt].add(src)

    # Calculate degree for each symbol (sum of incoming and outgoing edges)
    degrees = {sym: 0 for sym in symbols}
    for src, tgt in edges:
        if src in degrees:
            degrees[src] += 1
        if tgt in degrees:
            degrees[tgt] += 1

    # Initialize labels to directory prefixes
    labels = {}
    for sym, fp in symbols.items():
        if fp:
            fp_norm = fp.replace("\\", "/")
            parts = fp_norm.split("/")
            if len(parts) > 1:
                labels[sym] = "/".join(parts[:-1]) + "/"
            else:
                labels[sym] = "./"
        else:
            labels[sym] = "external/"

    # Run LPA for 5 iterations
    # Seed random for determinism under tests
    random.seed(42)
    for _ in range(5):
        nodes = list(symbols.keys())
        random.shuffle(nodes)
        for u in nodes:
            neighbors = adj[u]
            if not neighbors:
                continue
            # Count neighbor label frequencies
            freq = {}
            for v in neighbors:
                lbl = labels[v]
                freq[lbl] = freq.get(lbl, 0) + 1
            # Find maximum frequency label
            max_freq = max(freq.values())
            candidates = [lbl for lbl, count in freq.items() if count == max_freq]
            # Tie breaking: prefer current label if candidate, else deterministic choice
            if labels[u] in candidates:
                continue
            # Sort candidates for determinism
            candidates.sort()
            labels[u] = candidates[0]

    # Group nodes by community label
    communities = {}
    for sym, lbl in labels.items():
        communities.setdefault(lbl, []).append(sym)

    # Calculate inter-community connections
    # connections[comm_a][comm_b] = weight
    connections = {}
    for src, tgt in edges:
        lbl_src = labels.get(src)
        lbl_tgt = labels.get(tgt)
        if lbl_src and lbl_tgt and lbl_src != lbl_tgt:
            connections.setdefault(lbl_src, {}).setdefault(lbl_tgt, 0)
            connections[lbl_src][lbl_tgt] += 1

    return communities, connections, degrees


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
            results = repository.semantic_search(embedding, limit=limit)
            
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
        symbols = repository.get_symbols_in_file(filepath)
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
        closure = repository.get_transitive_closure(symbol, max_depth=max_depth)
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
        violations = auditor.run_audit(filepath_filter=filepath)
    except Exception as e:
        return f"Error running compliance audit: {e}"
    finally:
        db_conn.close()

    if not violations:
        scope = f"for `{filepath}`" if filepath else "project-wide"
        return f"## Compliance Audit\n\n**No boundary rule violations found** {scope}."

    md = [f"## Compliance Audit: {len(violations)} violation(s) found\n"]
    for i, v in enumerate(violations, 1):
        md.append(f"{i}. **[{v['rule_id']}]** (File: `{v['filepath']}:L{v['line']}`)")
        md.append(f"   - **Caller Symbol**: `{v['symbol']}`")
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
        totals = repository.get_repo_totals()
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


if __name__ == "__main__":
    # Start the FastMCP server (standard stdin/stdout communication)
    mcp.run()
