import sys

from utils.session import workspace_session


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
