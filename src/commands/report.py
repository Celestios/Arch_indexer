import sys

from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("report", help="Generate workspace data reports")
    p.add_argument("name", choices=["overview", "compliance"], help="Report name")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_report)


def cmd_report(args):
    """Generates a codebase report."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        from reporter.generator import Reporter
        reporter = Reporter(repository)
        try:
            report_text = reporter.generate_report(args.name, args.format)
            print(report_text)
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
