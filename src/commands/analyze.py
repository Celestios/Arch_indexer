import sys

from interface.tools.analyze import handle_analyze
from utils.session import get_project_root


def register(subparsers):
    p = subparsers.add_parser("analyze", help="Validate configuration completeness and sanity")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_analyze)


def cmd_analyze(args):
    """Validates the architectural configuration ontology (config.json) completeness and sanity."""
    report_text, ok = handle_analyze(get_project_root(args))
    print(report_text)
    sys.exit(0 if ok else 1)
