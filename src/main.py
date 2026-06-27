import sys
import argparse
from pathlib import Path

from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from engines.scip_wrapper import ScipWrapper
from auditor.analyzer import Auditor


def cmd_init(args):
    """Initialize workspace: create .arch/, deploy config, setup DB schema."""
    project_root = Path(args.project_root).resolve()
    arch_dir = initialize_workspace(project_root)
    print(f"Workspace initialized at {arch_dir}")


def cmd_index(args):
    """Index a project: detect languages, run SCIP parser, ingest to DB."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"

    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    languages = ScipWrapper.detect_languages(project_root)
    if not languages:
        print("No supported languages detected (Dart, Rust).")
        return

    print(f"Detected languages: {', '.join(languages)}")

    for lang in languages:
        index_path = ScipWrapper.run_indexer(project_root, lang)
        if index_path:
            print(f"[{lang}] Index generated at {index_path}")
            parsed = ScipWrapper.parse_index(index_path)
            ScipWrapper.ingest_index(repository, parsed)
            print(f"[{lang}] {len(parsed['symbols'])} symbols ingested.")
        else:
            print(f"[{lang}] Indexing failed or skipped.", file=sys.stderr)

    db_conn.close()
    print("Indexing complete.")


def cmd_audit(args):
    """Run architectural compliance audit."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"

    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    auditor = Auditor(repository, project_root)
    violations = auditor.run_audit()

    if violations:
        print(f"\nFound {len(violations)} violations:")
        for v in violations:
            print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} — {v['message']}")
    else:
        print("No violations found.")

    db_conn.close()


def main():
    parser = argparse.ArgumentParser(
        prog="arch",
        description="Arch-mcp: Agent-Native Code Intelligence & Compliance Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize workspace")
    init_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    init_parser.set_defaults(func=cmd_init)

    # index
    index_parser = subparsers.add_parser("index", help="Index project symbols")
    index_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    index_parser.set_defaults(func=cmd_index)

    # audit
    audit_parser = subparsers.add_parser("audit", help="Run compliance audit")
    audit_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    audit_parser.set_defaults(func=cmd_audit)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
