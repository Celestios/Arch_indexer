from pathlib import Path

from auditor.validator import ConfigValidator


def handle_analyze(project_root: Path) -> str:
    """Validate the architectural configuration ontology. Returns markdown."""
    validator = ConfigValidator(project_root)
    res = validator.validate()

    md = ["# Configuration Ontology Validation Report\n"]

    if res["success"]:
        md.append("\u2705 **Ontology validation passed successfully.**\n")
    else:
        md.append("\u274c **Ontology validation failed with errors.**\n")

    if res["warnings"]:
        md.append("### Warnings")
        for warning in res["warnings"]:
            md.append(f"- \u26a0\ufe0f {warning}")
        md.append("")

    if res["errors"]:
        md.append("### Errors")
        for error in res["errors"]:
            md.append(f"- \ud83d\uded1 {error}")
        md.append("")
    else:
        md.append("\u2705 Referential integrity validation passed.\n")

    return "\n".join(md)
