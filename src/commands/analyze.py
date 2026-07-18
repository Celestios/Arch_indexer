import sys

from auditor.validator import ConfigValidator
from utils.session import get_project_root


def cmd_analyze(args):
    """Validates the architectural configuration ontology (config.json) completeness and sanity."""
    project_root = get_project_root(args)
    validator = ConfigValidator(project_root)
    res = validator.validate()

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
