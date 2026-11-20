import json
import sys
from pathlib import Path
from db.connection import DbConnection
from db.repository import Repository

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

> [!NOTE]
> If a file is at `lib/ui/widgets/button.dart`, and both `"lib/"` and `"lib/ui/"` configurations exist, `lib/ui/` is selected because its path prefix length is greater. Path separators are normalized automatically (both `\\\\` and `/` match).

---

## 2. Field Classification Definitions

Fields act as architectural variables used to classify symbols (classes, methods, functions) and files. Configurations support two categories of fields: `manual_fields` and `automatic_fields`.

### A. Manual Fields (`manual_fields`)
These are metadata values assigned manually to files via the command line or MCP interface (e.g. `arch set-fields`).

| Parameter | Type | Description |
| :--- | :--- | :--- |
| `default` | `String` | The fallback value assigned if no override is provided. |
| `values` | `List[String]` | (Optional) The list of permitted values. If a manual entry isn't in this list, `Arch` automatically resets it to the `default` and marks the file as pending re-audit. |
| `reset_on_change` | `Boolean` | (Optional, default: `false`) If `true`, the manual value resets to the `default` value whenever the file contents change. |

*Example Syntax:*
```json
"manual_fields": {
  "stability": {
    "default": "experimental",
    "values": ["experimental", "stable", "deprecated"],
    "reset_on_change": true
  }
}
```

### B. Automatic Fields (`automatic_fields`)
These are metadata values assigned automatically by `Arch` during indexing. Each code symbol is classified by evaluating a list of conditions in order.

| Parameter | Type | Description |
| :--- | :--- | :--- |
| `default` | `String` | The default classification if no assignment rules are matched. |
| `values` | `List[String]` | All possible classifications that this field can hold. |
| `assignment_rules` | `List[Object]` | A list of rules checked in order (first match wins). |
| `handler` | `String` | (Optional) Configures special evaluation modes. Allowed: `"dependency_check"` (default direct calls checking) or `"propagation"` (transitive propagation). |

#### Assignment Rules & Conditions
Each entry in the `assignment_rules` list specifies a target `value` and a map of `conditions` that must all evaluate to `true` for a symbol to receive that value.

Supported condition types:
* `path_prefix`: Matches if the symbol is defined in a file whose path starts with this prefix.
* `class_suffix`: Matches if the symbol's name ends with the specified suffix (e.g. `"Controller"`, `"Service"`).
* `class_contains` / `name_contains`: Matches if the symbol's name contains the specified substring.
* `calls_prefix`: Matches if the symbol makes direct calls to any symbol defined in a file matching the given path prefix.

*Example Syntax:*
```json
"automatic_fields": {
  "layer": {
    "values": ["Presentation", "Domain", "Infrastructure"],
    "default": "Domain",
    "assignment_rules": [
      {
        "value": "Presentation",
        "conditions": {
          "path_prefix": "lib/ui",
          "class_suffix": "Widget"
        }
      },
      {
        "value": "Infrastructure",
        "conditions": {
          "calls_prefix": "lib/db"
        }
      }
    ]
  }
}
```

---

## 3. Compliance Rules (`rules`)

Compliance rules define constraints that trigger violations during boundary audits. Rules can be declared at the **prefix level** or inside an **automatic field block**.

`Arch` supports three rule types:

### A. Dependency Check (`dependency_check`)
Asserts that direct calls/dependencies from a source classification value to a target classification value are forbidden. This is the default rule type if `rule_type` is omitted.

* **Syntax Parameters**:
  * `source`: The field classification of the calling symbol.
  * `target`: The field classification of the called (callee) symbol.
  * `message`: (Optional) A custom message printed when the violation is found.

*Example:*
```json
"rules": [
  {
    "rule_type": "dependency_check",
    "source": "Presentation",
    "target": "Infrastructure",
    "message": "Presentation components cannot call Infrastructure resources directly."
  }
]
```

### B. Package Restrictions (`package_restriction`)
Restricts symbols of a specific classification from calling or depending on third-party frameworks/packages.

* **Syntax Parameters**:
  * `rule_type`: Must be `"package_restriction"`.
  * `source`: The field classification of the calling symbol.
  * `blocklist`: A list of package prefix globs that are forbidden (e.g. `"package:sqflite/*"`).
  * `message`: (Optional) Custom error message.

*Example:*
```json
"rules": [
  {
    "rule_type": "package_restriction",
    "source": "Domain",
    "blocklist": ["package:flutter/*", "package:sqflite/*"],
    "message": "Domain business logic must not depend on UI or Database frameworks."
  }
]
```

### C. Naming Conventions (`naming_convention`)
Enforces naming suffix or prefix constraints on symbols that match a specific classification.

* **Syntax Parameters**:
  * `rule_type`: Must be `"naming_convention"`.
  * `classification`: The field value target (applies when any field matches this value).
  * `name_prefix`: (Optional) Symbol must start with this prefix.
  * `name_suffix`: (Optional) Symbol must end with this suffix.
  * `message`: (Optional) Custom error message.

*Example:*
```json
"rules": [
  {
    "rule_type": "naming_convention",
    "classification": "Presentation",
    "name_suffix": "Widget",
    "message": "Presentation layer components must be suffixed with 'Widget'."
  }
]
```

---

## 4. Metadata Propagation

When an automatic field's `handler` is configured as `"propagation"`, classifications automatically flow transitively across call paths. Instead of only checking direct calls, `Arch` tracks transitive dependencies.

```
[Presentation Component] ──> [Domain Service] ──> [Infrastructure Client]
           │                                                ▲
           └────────────────── (Transitive Call) ───────────┘
```

### Propagation Syntax
Within an automatic field configuration, specify the following parameters:

* `propagation_direction`: Direction to propagate values along the call graph.
  * `"upstream"` (Default): Callee properties propagate to callers (e.g. calling an Infrastructure method transitively tags the caller as Infrastructure).
  * `"downstream"`: Caller properties propagate to callees.
* `weights`: Map of classification values to integer priorities. Higher weights override lower weights during propagation conflicts. If omitted, priority is determined by the index order inside `values`.
* `barriers`: List of values that block propagation from passing through a symbol.
* `barrier_field`: The field name checked against the `barriers` list (defaults to the field's own name).

*Example:*
```json
"layer": {
  "values": ["Presentation", "Domain", "Infrastructure"],
  "default": "Domain",
  "handler": "propagation",
  "propagation_direction": "upstream",
  "barriers": ["Domain"],
  "barrier_field": "layer",
  "rules": [
    {
      "source": "Presentation",
      "target": "Infrastructure",
      "message": "Presentation layer cannot transitively call Infrastructure layer."
    }
  ]
}
```

> [!TIP]
> Setting `"barriers": ["Domain"]` means any symbol classified as `"Domain"` acts as a barrier, stopping `"Infrastructure"` properties from propagating further upstream (insulating the Presentation layer from transitive infrastructure dependencies). If a violation occurs, the compliance report lists the complete call chain trace.

---

## 5. Outcome: Call Graph Edge Weights

Symbol and file classifications defined in `config.json` automatically tune the coupling weights inside the workspace dependency graph:

1. **Same-Layer Boost (x1.5)**: If a caller and callee symbol share the exact same `layer` value, the connection weight is multiplied by **`1.5`** (represents natural cohesive coupling).
2. **Layer Tier Boundaries (x0.5)**: If symbols have a `tier` field with numerical values (e.g. `"1"`, `"2"`), calls from a higher tier to a lower tier (e.g., `2 -> 1`) have their weight multiplied by **`0.5`** (incentivizes downward dependency flow).
3. **Barrier Insulation (x0.3)**: If the calling symbol's `architectural_role` or `role` is defined in a propagation `barriers` list, the edge weight is multiplied by **`0.3`** (penalizes or reduces weight across architectural boundaries).

---

## 6. Comprehensive Configuration Example

Below is a complete, realistic `.arch/config.json` showcasing all matching, field definitions, rules, and propagation options.

```json
{
  "lib/": {
    "manual_fields": {
      "stability": {
        "values": ["stable", "legacy", "experimental"],
        "default": "experimental",
        "reset_on_change": true
      }
    },
    "automatic_fields": {
      "layer": {
        "values": ["Presentation", "Application", "Domain", "Infrastructure"],
        "default": "Domain",
        "assignment_rules": [
          {
            "value": "Presentation",
            "conditions": {
              "path_prefix": "lib/ui"
            }
          },
          {
            "value": "Infrastructure",
            "conditions": {
              "path_prefix": "lib/infra"
            }
          }
        ],
        "handler": "propagation",
        "propagation_direction": "upstream",
        "barriers": ["Domain"],
        "barrier_field": "layer",
        "weights": {
          "Presentation": 1,
          "Application": 2,
          "Domain": 3,
          "Infrastructure": 4
        },
        "rules": [
          {
            "rule_type": "dependency_check",
            "source": "Presentation",
            "target": "Infrastructure",
            "message": "Presentation layer components must not call Infrastructure directly or transitively."
          },
          {
            "rule_type": "package_restriction",
            "source": "Domain",
            "blocklist": ["package:flutter/*", "package:sqflite/*"],
            "message": "Domain business logic must not depend directly on database or framework libraries."
          },
          {
            "rule_type": "naming_convention",
            "classification": "Presentation",
            "name_suffix": "Widget",
            "message": "Presentation layer components must end with the suffix 'Widget'."
          }
        ]
      }
    }
  }
}
```

---

## 7. Architectural Configuration Discoveries Report

This section summarizes critical architectural facts, undocumented mechanics, and validation behaviors learned about the `Arch` linter:

### 🔍 Static Value Reachability Checks
The `analyze` tool performs static reachability analysis on defined value arrays. 
* **Rule**: If you define permitted classifications in a `values` array for automatic fields, the validator demands that each value be reachable (either designated as the `default` or explicitly assigned via at least one entry in `assignment_rules`). Declaring unused fallback values is flagged as dead configuration.
* **Warning Pattern**:
  - `Prefix '<scope>' field '<field>': Values that are defined but not used: ['<value1>', '<value2>']`

### 🗃️ Scope Isolation & Duplicate Definitions
* **Rule**: Manual fields (such as `ai_summary` or `design_pattern`) must be declared individually under each top-level scope block (`"lib"`, `"rust"`, etc.) if you want them to apply to files under those directories.
* **Discovery**: There is no global/shared namespace for fields. Every scope functions as an independent configuration environment. 

### 📂 Predefined Scopes Constraint
* **Rule**: The linter is hard-configured with a fixed set of top-level scopes: `lib`, `packages`, `rust`, and `test` (matching the root directories). All path assignments within these blocks (using `path_prefix`) must be absolute relative to the workspace root.
* **Discovery**: Changing the keys to use trailing slashes (e.g. `"lib/"`) or adding custom root scopes (e.g. `"integration_test/"`) bypassed checks or caused matching failures.

---

## 8. Path-to-Tier Classification Mapping Reference

The validated workspace configuration uses the following mapping:

* **Tier 1 (Presentation & Interface)**: Maps `lib/features/graph/ui`, `lib/features/workspace/ui`, `lib/presentation`, `lib/shared/widgets`, FFI Bridge bindings (`lib/src/rust/bridge`), and the Rust FFI API (`rust/src/bridge`).
* **Tier 2 (Coordination & Solvers)**: Maps `lib/features/graph/presentation` (view states), `lib/features/graph/engine` (gesture interceptor state machine), command objects, and the Rust-side pathfinding/shaping algorithms (`rust/src/domain/relation_engine`).
* **Tier 3 (Domain Core & SurrealDB)**: Maps graph entity structures (`lib/features/graph/models`), stores (`lib/features/graph/store`), the SurrealDB database connector (`rust/src/persistence`), and zip packaging (`rust/src/format`).
* **Test Isolation**: All test files are automatically isolated to `Tier 1`, allowing them to safely import components from Tiers 1, 2, and 3 without triggering dependency violations.
"""


def sync_rules_to_db(repository: Repository, config: dict):
    """Sync all architectural rules from config to compliance_rules table."""
    if not isinstance(config, dict):
        return

    for prefix, prefix_conf in config.items():
        if not isinstance(prefix_conf, dict):
            continue

        # Top-level prefix rules
        for rule in prefix_conf.get("rules", []):
            if not isinstance(rule, dict):
                continue
            rule_type = rule.get("rule_type", "dependency_check")
            severity = rule.get("severity", "Error")
            if rule_type == "package_restriction":
                source = rule.get("source", "*")
                msg = rule.get("message", f"Package restriction: {source} cannot depend on blocklist")
                rule_id = f"{prefix}_pkg_{source}".lower().replace("/", "_").replace(".", "_")
                repository.quality.upsert_rule(rule_id, msg, severity)
            elif rule_type == "naming_convention":
                classification = rule.get("classification", "*")
                msg = rule.get("message", f"Naming convention for {classification}")
                rule_id = f"{prefix}_naming_{classification}".lower().replace("/", "_").replace(".", "_")
                repository.quality.upsert_rule(rule_id, msg, severity)
            else:
                source = rule.get("source", "*")
                target = rule.get("target", "*")
                msg = rule.get("message", f"Dependency violation: {source} -> {target}")
                rule_id = f"{prefix}_{source}_{target}".lower().replace("/", "_").replace(".", "_")
                repository.quality.upsert_rule(rule_id, msg, severity)

        # Field-level rules
        auto_fields = prefix_conf.get("automatic_fields", {})
        for field_name, field_conf in auto_fields.items():
            if not isinstance(field_conf, dict):
                continue
            handler = field_conf.get("handler", "dependency_check")
            for rule in field_conf.get("rules", []):
                if not isinstance(rule, dict):
                    continue
                rule_type = rule.get("rule_type", handler)
                severity = rule.get("severity", "Error")
                if rule_type == "package_restriction":
                    source = rule.get("source", "*")
                    msg = rule.get("message", f"Package restriction: {source} cannot depend on blocklist")
                    rule_id = f"{prefix}_{field_name}_pkg_{source}".lower().replace("/", "_").replace(".", "_")
                    repository.quality.upsert_rule(rule_id, msg, severity)
                elif rule_type == "naming_convention":
                    classification = rule.get("classification", "*")
                    msg = rule.get("message", f"Naming convention for {classification}")
                    rule_id = f"{prefix}_{field_name}_naming_{classification}".lower().replace("/", "_").replace(".", "_")
                    repository.quality.upsert_rule(rule_id, msg, severity)
                else:
                    source = rule.get("source", "*")
                    target = rule.get("target", "*")
                    msg = rule.get("message", f"Dependency violation: {source} -> {target}")
                    rule_id = f"{prefix}_{field_name}_{source}_{target}".lower().replace("/", "_").replace(".", "_")
                    repository.quality.upsert_rule(rule_id, msg, severity)


def initialize_workspace(project_root: Path) -> Path:
    """
    Initializes the workspace: creates output folders, deploys a default config.json,
    deploys a config_guide.md, initializes the database schema, and loads
    configuration rules into the DB.
    """
    arch_dir = project_root / ".arch"
    arch_dir.mkdir(parents=True, exist_ok=True)

    config_file = arch_dir / "config.json"
    guide_file = arch_dir / "config_guide.md"

    # 1. Deploy default config.json if not present
    if not config_file.exists():
        print(f"Deploying default configuration rules to {config_file}...")
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG_JSON, f, indent=2)
        except Exception as e:
            print(f"Error deploying config.json: {e}", file=sys.stderr)
            raise e
    else:
        print(f"Configuration file already exists at {config_file}.")

    # Deploy configuration guide if not present
    if not guide_file.exists():
        print(f"Deploying configuration guide to {guide_file}...")
        try:
            with open(guide_file, "w", encoding="utf-8") as f:
                f.write(CONFIG_GUIDE_CONTENT)
        except Exception as e:
            print(f"Warning: Failed to deploy config_guide.md: {e}", file=sys.stderr)
    else:
        print(f"Configuration guide already exists at {guide_file}.")

    # 2. Initialize the database connection & schema
    db_path = arch_dir / "arch.db"
    print(f"Initializing database at {db_path}...")
    db_conn = DbConnection(db_path)
    repository = Repository(db_conn)

    try:
        db_conn.get_connection()

        # 3. Read config.json and sync compliance rules to the database
        print("Syncing architectural rules to compliance catalog...")
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            sync_rules_to_db(repository, config)
            print("Architectural compliance rules successfully synchronized.")
        except Exception as e:
            print(f"Warning: Failed to synchronize compliance rules from config.json: {e}", file=sys.stderr)

        # 4. Historical git co-change coupling ingestion (disabled)
        # try:
        #     from change_tracker.git_coupling import GitCouplingMiner
        #     pairs_count = GitCouplingMiner.mine_git_co_changes(project_root, repository)
        #     if pairs_count > 0:
        #         print(f"Mined {pairs_count} historical git co-change relationships.")
        # except Exception:
        #     pass

        # 5. Register in machine-wide daemon registry
        try:
            from utils.single_instance import register_workspace
            register_workspace(project_root)
        except Exception:
            pass
    except Exception as e:
        print(f"Failed to initialize database schema: {e}", file=sys.stderr)
        raise e
    finally:
        db_conn.close()

    return arch_dir


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    try:
        initialize_workspace(project_root)
        print("Workspace successfully initialized.")
    except Exception as err:
        print(f"Initialization failed: {err}", file=sys.stderr)
        sys.exit(1)
