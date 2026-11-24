import json
import logging
import sys
from pathlib import Path

from db.connection import DbConnection
from db.repository import Repository
from utils.arch_config import ArchConfig, build_rule_id
from utils.helpers import load_config

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_JSON = {}

CONFIG_GUIDE_CONTENT = """# Guide to Arch Architectural Configuration: `config.json`

This guide explains how to define project-wide architectural constraints, symbol classification rules, and boundary checks in `Arch` using the `.arch/config.json` file.

---

## 1. File Location and Match Resolution

The configuration is defined in a single file located at the root of the project:
`[project_root]/.arch/config.json`

### Path Matching Hierarchy
* The file is structured as a JSON object where each key represents a **path prefix** (e.g., `"src/"`, `"lib/ui/"`).
* A special key `.` represents fallback configuration for files in the root directory.
* When `Arch` evaluates a source file, it resolves the applicable configuration using a **longest matching prefix** strategy.

---

## 2. Field Classification Definitions

Configurations support two categories of fields: `manual_fields` and `automatic_fields`.

### A. Manual Fields (`manual_fields`)
Metadata values assigned manually to files via CLI or MCP (`set_fields`).

### B. Automatic Fields (`automatic_fields`)
Metadata values assigned automatically during indexing via `assignment_rules`, with optional transitive `"handler": "propagation"` and `rules` (`dependency_check`, `package_restriction`, `naming_convention`).
"""


def sync_rules_to_db(repository: Repository, config: ArchConfig):
    """Sync all architectural rules from ArchConfig to compliance_rules table."""
    if not config:
        return

    for prefix, prefix_conf in config.items():
        for field_name, field_conf in prefix_conf.automatic_fields.items():
            handler = field_conf.get("handler", "dependency_check")
            for rule in field_conf.get("rules", []):
                rule_type = rule.get("rule_type", handler)
                severity = rule.get("severity", "Error")
                if rule_type == "package_restriction":
                    source = rule.get("source", "*")
                    msg = rule.get("message", f"Package restriction: {source} cannot depend on blocklist")
                    rule_id = build_rule_id(prefix, field_name, rule_type, source=source)
                elif rule_type == "naming_convention":
                    classification = rule.get("classification", "*")
                    msg = rule.get("message", f"Naming convention for {classification}")
                    rule_id = build_rule_id(prefix, field_name, rule_type, classification=classification)
                else:
                    source = rule.get("source", "*")
                    target = rule.get("target", "*")
                    msg = rule.get("message", f"Dependency violation: {source} -> {target}")
                    rule_id = build_rule_id(prefix, field_name, rule_type, source=source, target=target)
                repository.quality.upsert_rule(rule_id, msg, severity)


def initialize_workspace(project_root: Path) -> Path:
    """Initializes .arch workspace, config, guide, database schema, and compliance rules."""
    arch_dir = project_root / ".arch"
    arch_dir.mkdir(parents=True, exist_ok=True)

    config_file = arch_dir / "config.json"
    guide_file = arch_dir / "config_guide.md"

    if not config_file.exists():
        logger.info("Deploying default configuration rules to %s...", config_file)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG_JSON, f, indent=2)

    if not guide_file.exists():
        try:
            with open(guide_file, "w", encoding="utf-8") as f:
                f.write(CONFIG_GUIDE_CONTENT)
        except OSError as e:
            logger.warning("Failed to deploy config_guide.md: %s", e)

    db_path = arch_dir / "arch.db"
    db_conn = DbConnection(db_path)
    repository = Repository(db_conn)

    try:
        db_conn.get_connection()
        try:
            sync_rules_to_db(repository, load_config(project_root))
        except Exception as e:
            logger.warning("Failed to synchronize compliance rules from config.json: %s", e)

        try:
            from utils.single_instance import register_workspace
            register_workspace(project_root)
        except Exception:
            pass
    finally:
        db_conn.close()

    return arch_dir


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    try:
        initialize_workspace(project_root)
    except Exception as err:
        logger.error("Initialization failed: %s", err)
        sys.exit(1)
