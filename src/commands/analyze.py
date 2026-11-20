import sys

from utils.arch_config import ArchConfig
from utils.session import get_project_root


def register(subparsers):
    p = subparsers.add_parser("analyze", help="Validate configuration completeness and sanity")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_analyze)


def cmd_analyze(args):
    """Validates the architectural configuration ontology (config.json) completeness and sanity."""
    project_root = get_project_root(args)
    _, res = ArchConfig.parse_and_validate(project_root)

    print("=== Configuration Sanity & Completeness Analysis ===")
    
    if res["warnings"]:
        print(f"\n[WARNING] Reachability warnings ({len(res['warnings'])}):")
        for warning in res["warnings"]:
            print(f"  - {warning}")
    else:
        print("\n[OK] Value reachability check passed (no unreachable values).")

    if res["errors"]:
        print(f"\n[ERROR] Referential integrity failures ({len(res['errors'])}):")
        for error in res["errors"]:
            print(f"  - {error}")
        print("\nValidation failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("[OK] Referential integrity validation passed.")
        print("\nValidation succeeded.")
        sys.exit(0)
