"""Shared handler for architectural configuration ontology validation."""
from pathlib import Path
from typing import Tuple

from utils.arch_config import ArchConfig


def handle_analyze(project_root: Path) -> Tuple[str, bool]:
    """Validates .arch/config.json and returns (formatted_report, success)."""
    _, res = ArchConfig.parse_and_validate(project_root)
    lines = ["=== Configuration Sanity & Completeness Analysis ==="]

    if res["warnings"]:
        lines.append(f"\n[WARNING] Reachability warnings ({len(res['warnings'])}):")
        for warning in res["warnings"]:
            lines.append(f"  - {warning}")
    else:
        lines.append("\n[OK] Value reachability check passed (no unreachable values).")

    if res["errors"]:
        lines.append(f"\n[ERROR] Referential integrity failures ({len(res['errors'])}):")
        for error in res["errors"]:
            lines.append(f"  - {error}")
        lines.append("\nValidation failed.")
        return "\n".join(lines), False

    lines.append("[OK] Referential integrity validation passed.")
    lines.append("\nValidation succeeded.")
    return "\n".join(lines), True
