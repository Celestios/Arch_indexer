import sys

from db.connection import DbConnection
from db.repository import Repository
from utils.session import get_project_root


def register(subparsers):
    p = subparsers.add_parser("impact", help="Perform blast radius / transitive dependency analysis for a symbol")
    p.add_argument("symbol", help="Target symbol name")
    p.add_argument("--max-depth", type=int, default=3, help="Maximum traversal depth (default: 3)")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_impact)


def cmd_impact(args):
    """Performs blast radius analysis for a symbol by computing its transitive callers and callees."""
    project_root = get_project_root(args)
    arch_dir = project_root / ".arch"
    db_path = arch_dir / "arch.db"

    if not db_path.exists():
        print(f"Error: Arch database not found at {db_path}. Please run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(db_path)
    repository = Repository(db_conn)

    try:
        closure = repository.edges.get_transitive_closure(args.symbol, max_depth=args.max_depth)
    except Exception as e:
        print(f"Error computing blast radius: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db_conn.close()

    upstream = closure.get("upstream", [])
    downstream = closure.get("downstream", [])

    print(f"=== Blast Radius for: {args.symbol} ===")
    
    print("\n--- Upstream Callers (Who calls this?) ---")
    if not upstream:
        print("*No transitive upstream callers found.*")
    else:
        upstream_sorted = sorted(upstream, key=lambda x: x["depth"])
        for item in upstream_sorted:
            path_str = " ──> ".join(f"{s.split('.')[-1]}" for s in item["path"])
            print(f"- {item['symbol']} [Depth: {item['depth']}]")
            print(f"  Path: {path_str}")

    print("\n--- Downstream Callees (What does this call?) ---")
    if not downstream:
        print("*No transitive downstream callees found.*")
    else:
        downstream_sorted = sorted(downstream, key=lambda x: x["depth"])
        for item in downstream_sorted:
            path_str = " ──> ".join(f"{s.split('.')[-1]}" for s in item["path"])
            print(f"- {item['symbol']} [Depth: {item['depth']}]")
            print(f"  Path: {path_str}")
