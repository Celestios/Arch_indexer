import sys
import argparse

from commands import (
    cmd_init,
    cmd_audit,
    cmd_report,
    cmd_watch,
    cmd_analyze,
    cmd_impact,
    cmd_set_status,
    cmd_set_fields,
    cmd_clear_pending,
    cmd_mcp,
)


def main():

    parser = argparse.ArgumentParser(
        prog="arch",
        description="Arch-mcp: Agent-Native Code Intelligence & Compliance Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # mcp
    mcp_parser = subparsers.add_parser("mcp", help="Start the MCP server")
    mcp_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    mcp_parser.set_defaults(func=cmd_mcp)

    # init (unified setup + indexer)
    init_parser = subparsers.add_parser("init", help="Initialize workspace, download models, and index symbols")
    init_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    init_parser.add_argument("--force", action="store_true", help="Force clean rebuild: delete DB and re-index from scratch")
    init_parser.set_defaults(func=cmd_init)

    # audit
    audit_parser = subparsers.add_parser("audit", help="Run compliance audit")
    audit_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    audit_parser.set_defaults(func=cmd_audit)

    # report
    report_parser = subparsers.add_parser("report", help="Generate workspace data reports")
    report_parser.add_argument("name", choices=["overview", "compliance"], help="Report name")
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    report_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    report_parser.set_defaults(func=cmd_report)

    # set-status
    set_status_parser = subparsers.add_parser("set-status", help="Set manual AI logical compliance status for a file")
    set_status_parser.add_argument("filepath", help="Filepath to the target file")
    set_status_parser.add_argument("status", choices=["COMPLIANT", "VIOLATION_DETECTED"], help="Manual logical compliance status")
    set_status_parser.add_argument("justification", nargs="?", default=None, help="Justification comment (required for VIOLATION_DETECTED)")
    set_status_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    set_status_parser.set_defaults(func=cmd_set_status)

    # set-fields
    set_fields_parser = subparsers.add_parser("set-fields", help="Set manual metadata fields for a file")
    set_fields_parser.add_argument("filepath", help="Filepath to the target file")
    set_fields_parser.add_argument("fields_json", help="JSON string of fields to update")
    set_fields_parser.add_argument("justification", nargs="?", default=None, help="Optional update justification")
    set_fields_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    set_fields_parser.set_defaults(func=cmd_set_fields)

    # clear-pending
    clear_pending_parser = subparsers.add_parser("clear-pending", help="Clear all pending audit flags")
    clear_pending_parser.add_argument("justification", help="Justification comment for clearing all pending audits")
    clear_pending_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    clear_pending_parser.set_defaults(func=cmd_clear_pending)

    # watch
    watch_parser = subparsers.add_parser("watch", help="Watch workspace and auto-index and audit on changes")
    watch_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    watch_parser.add_argument("--debounce", type=float, default=3.0, help="Debounce delay in seconds")
    watch_parser.set_defaults(func=cmd_watch)

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Validate configuration completeness and sanity")
    analyze_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    analyze_parser.set_defaults(func=cmd_analyze)

    # impact
    impact_parser = subparsers.add_parser("impact", help="Perform blast radius / transitive dependency analysis for a symbol")
    impact_parser.add_argument("symbol", help="Target symbol name")
    impact_parser.add_argument("--max-depth", type=int, default=3, help="Maximum traversal depth (default: 3)")
    impact_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    impact_parser.set_defaults(func=cmd_impact)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
