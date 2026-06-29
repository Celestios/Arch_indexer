import json
from pathlib import Path
from typing import Dict, List, Any

class ConfigValidator:
    """
    Validates structural correctness, completeness, and referential integrity of the config.json.
    """
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_path = project_root / ".arch" / "config.json"

    def validate(self) -> Dict[str, Any]:
        """
        Executes validation.
        Returns:
            {
                "success": bool,
                "errors": List[str],
                "warnings": List[str]
            }
        """
        errors = []
        warnings = []

        # 1. JSON Syntax and file existence checks
        if not self.config_path.exists():
            errors.append(f"Configuration file not found at {self.config_path}")
            return {"success": False, "errors": errors, "warnings": warnings}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"Failed to parse config.json as JSON: {e}")
            return {"success": False, "errors": errors, "warnings": warnings}
        except Exception as e:
            errors.append(f"Failed to read config.json: {e}")
            return {"success": False, "errors": errors, "warnings": warnings}

        # 2. Structural checks
        if not isinstance(config, dict):
            errors.append("Top-level configuration must be a JSON object (dictionary)")
            return {"success": False, "errors": errors, "warnings": warnings}

        for prefix, prefix_conf in config.items():
            if not isinstance(prefix_conf, dict):
                errors.append(f"Prefix '{prefix}' configuration must be a JSON object")
                continue

            manual_fields = prefix_conf.get("manual_fields", {})
            auto_fields = prefix_conf.get("automatic_fields", {})

            if not isinstance(manual_fields, dict):
                errors.append(f"Prefix '{prefix}' manual_fields must be a JSON object")
                manual_fields = {}
            if not isinstance(auto_fields, dict):
                errors.append(f"Prefix '{prefix}' automatic_fields must be a JSON object")
                auto_fields = {}

            # Validate each field
            self._validate_fields(prefix, manual_fields, auto_fields, errors, warnings)

        success = len(errors) == 0
        return {
            "success": success,
            "errors": errors,
            "warnings": warnings
        }

    def _validate_fields(
        self,
        prefix: str,
        manual_fields: Dict[str, Any],
        auto_fields: Dict[str, Any],
        errors: List[str],
        warnings: List[str]
    ):
        # Helper to retrieve defined field config by name under this prefix
        def get_field_cfg(name):
            if name in auto_fields:
                return auto_fields[name]
            return manual_fields.get(name)

        # Merge fields for reference checks
        all_fields = {**manual_fields, **auto_fields}

        for field_name, field_conf in all_fields.items():
            if not isinstance(field_conf, dict):
                errors.append(f"Prefix '{prefix}' field '{field_name}' configuration must be a JSON object")
                continue

            default_val = field_conf.get("default")
            allowed_values = field_conf.get("values")

            # 3. Reachability checks (completeness) for automatic fields
            if allowed_values is not None and field_name in auto_fields:
                if not isinstance(allowed_values, list):
                    errors.append(f"Prefix '{prefix}' field '{field_name}' allowed values list must be a list")
                else:
                    # Collect all assignment values
                    assigned = set()
                    assignment_rules = field_conf.get("assignment_rules", [])
                    if isinstance(assignment_rules, list):
                        for rule in assignment_rules:
                            if isinstance(rule, dict) and "value" in rule:
                                assigned.add(rule["value"])
                    
                    unused_values = []
                    for val in allowed_values:
                        if val != default_val and val not in assigned:
                            unused_values.append(val)
                    
                    if unused_values:
                        warnings.append(
                            f"Prefix '{prefix}' field '{field_name}': Values that are defined but not used: {unused_values}"
                        )

            # 4. Dependency rules referential integrity
            rules = field_conf.get("rules", [])
            if rules:
                if not isinstance(rules, list):
                    errors.append(f"Prefix '{prefix}' field '{field_name}' rules must be a list")
                else:
                    for idx, rule in enumerate(rules):
                        if not isinstance(rule, dict):
                            errors.append(f"Prefix '{prefix}' field '{field_name}' rule at index {idx} must be a JSON object")
                            continue
                        source = rule.get("source")
                        target = rule.get("target")
                        if not source or not target:
                            errors.append(f"Prefix '{prefix}' field '{field_name}' rule at index {idx} must specify both 'source' and 'target'")
                            continue
                        
                        if allowed_values is not None:
                            if source not in allowed_values:
                                errors.append(f"Prefix '{prefix}' field '{field_name}' rule source '{source}' is not in allowed values list {allowed_values}")
                            if target not in allowed_values:
                                errors.append(f"Prefix '{prefix}' field '{field_name}' rule target '{target}' is not in allowed values list {allowed_values}")

            # 5. Propagation barriers referential integrity
            barriers = field_conf.get("barriers", [])
            if barriers:
                if not isinstance(barriers, list):
                    errors.append(f"Prefix '{prefix}' field '{field_name}' barriers must be a list")
                else:
                    # Retrieve the barrier field configurations
                    barrier_field_name = field_conf.get("barrier_field", "architectural_role")
                    barrier_field_cfg = get_field_cfg(barrier_field_name)

                    if not barrier_field_cfg:
                        errors.append(
                            f"Prefix '{prefix}' field '{field_name}' specifies barrier_field '{barrier_field_name}' which is not defined under this prefix"
                        )
                    else:
                        barrier_allowed_values = barrier_field_cfg.get("values")
                        if barrier_allowed_values is not None:
                            invalid_barriers = [b for b in barriers if b not in barrier_allowed_values]
                            if invalid_barriers:
                                errors.append(
                                    f"Prefix '{prefix}' field '{field_name}' barrier(s) {invalid_barriers} are not in allowed values list {barrier_allowed_values} of barrier_field '{barrier_field_name}'"
                                )
