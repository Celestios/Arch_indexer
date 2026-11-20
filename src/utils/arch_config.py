"""Typed, normalized domain model for `.arch/config.json`.

This module is deliberately dependency-free (stdlib only) and JSON-round-trippable.
It centralizes two invariants that were previously duplicated across consumers:

* top-level ``exclude`` is separated from directory ``prefixes``;
* every field configuration carries a single canonical ``barrier_field`` (the
  field's own name when not explicitly configured).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union


def _normalize_exclude(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(p) for p in value if p]
    if isinstance(value, str) and value:
        return [value]
    return []


class _MappingMixin:
    """Small read-only mapping helper shared by the config dataclasses."""

    def get(self, key: str, default: Any = None) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise KeyError(key)
        return value

    def __contains__(self, key: object) -> bool:
        sentinel = object()
        return self.get(key, sentinel) is not sentinel  # type: ignore[arg-type]


@dataclass
class FieldConfig(_MappingMixin):
    """A single field configuration with normalized defaults."""

    name: str
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, raw: Any) -> "FieldConfig":
        conf = dict(raw) if isinstance(raw, dict) else {}
        # Single source of truth for barrier resolution: explicit value, else own name.
        conf["barrier_field"] = conf.get("barrier_field") or name
        return cls(name=name, raw=conf)

    @property
    def barrier_field(self) -> str:
        return self.raw.get("barrier_field") or self.name

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def keys(self):
        return self.raw.keys()

    def values(self):
        return self.raw.values()

    def items(self):
        return self.raw.items()

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.raw)


@dataclass
class RuleConfig(_MappingMixin):
    """A single rule definition (kept dict-like for backwards compatibility)."""

    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> "RuleConfig":
        return cls(raw=dict(raw) if isinstance(raw, dict) else {})

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def keys(self):
        return self.raw.keys()

    def values(self):
        return self.raw.values()

    def items(self):
        return self.raw.items()

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.raw)


@dataclass
class PrefixConfig(_MappingMixin):
    """Configuration for one directory prefix."""

    name: str
    automatic_fields: Dict[str, FieldConfig] = field(default_factory=dict)
    manual_fields: Dict[str, FieldConfig] = field(default_factory=dict)
    rules: List[RuleConfig] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, raw: Any) -> "PrefixConfig":
        conf = dict(raw) if isinstance(raw, dict) else {}

        auto_raw = conf.get("automatic_fields")
        auto_fields = {}
        if isinstance(auto_raw, dict):
            auto_fields = {
                field_name: FieldConfig.from_dict(field_name, field_conf)
                for field_name, field_conf in auto_raw.items()
            }

        manual_raw = conf.get("manual_fields")
        manual_fields = {}
        if isinstance(manual_raw, dict):
            manual_fields = {
                field_name: FieldConfig.from_dict(field_name, field_conf)
                for field_name, field_conf in manual_raw.items()
            }

        rules_raw = conf.get("rules")
        rules = []
        if isinstance(rules_raw, list):
            rules = [RuleConfig.from_dict(r) for r in rules_raw if isinstance(r, dict)]

        return cls(
            name=name,
            automatic_fields=auto_fields,
            manual_fields=manual_fields,
            rules=rules,
            raw=conf,
        )

    def get(self, key: str, default: Any = None) -> Any:
        if key == "automatic_fields":
            return self.automatic_fields
        if key == "manual_fields":
            return self.manual_fields
        if key == "rules":
            return self.rules
        return self.raw.get(key, default)

    def keys(self):
        return self.raw.keys()

    def values(self):
        return self.raw.values()

    def items(self):
        return self.raw.items()

    def to_dict(self) -> Dict[str, Any]:
        conf = dict(self.raw)
        conf["automatic_fields"] = {
            name: field_conf.to_dict()
            for name, field_conf in self.automatic_fields.items()
        }
        conf["manual_fields"] = {
            name: field_conf.to_dict()
            for name, field_conf in self.manual_fields.items()
        }
        conf["rules"] = [rule.to_dict() for rule in self.rules]
        return conf


@dataclass
class ArchConfig(_MappingMixin):
    """Normalized representation of the whole architecture configuration.

    Dict-like access (``items``/``keys``/``values``/``get``/``in``/``len``/
    iteration) exposes **only** the directory prefixes. The top-level
    ``exclude`` list is available via the ``exclude`` attribute.
    """

    prefixes: Dict[str, PrefixConfig] = field(default_factory=dict)
    exclude: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> "ArchConfig":
        if not isinstance(raw, dict):
            return cls()

        prefixes: Dict[str, PrefixConfig] = {}
        exclude: List[str] = []
        extra: Dict[str, Any] = {}

        for key, value in raw.items():
            if key == "exclude":
                exclude = _normalize_exclude(value)
            elif isinstance(value, dict):
                prefixes[key] = PrefixConfig.from_dict(key, value)
            else:
                extra[key] = value

        return cls(prefixes=prefixes, exclude=exclude, extra=extra)

    @classmethod
    def validate_dict(cls, config: Any) -> Dict[str, Any]:
        """Validates structural correctness, completeness, and referential integrity of a config dict."""
        errors: List[str] = []
        warnings: List[str] = []

        if not isinstance(config, dict):
            errors.append("Top-level configuration must be a JSON object (dictionary)")
            return {"success": False, "errors": errors, "warnings": warnings}

        for prefix, prefix_conf in config.items():
            if prefix == "exclude":
                if not isinstance(prefix_conf, (list, str)):
                    errors.append("'exclude' must be a list of glob patterns or a string")
                continue

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

            all_fields = {**manual_fields, **auto_fields}

            def get_field_cfg(name: str):
                if name in auto_fields:
                    return auto_fields[name]
                return manual_fields.get(name)

            for field_name, field_conf in all_fields.items():
                if not isinstance(field_conf, dict):
                    errors.append(f"Prefix '{prefix}' field '{field_name}' configuration must be a JSON object")
                    continue

                default_val = field_conf.get("default")
                allowed_values = field_conf.get("values")

                # Reachability checks
                if allowed_values is not None and field_name in auto_fields:
                    if not isinstance(allowed_values, list):
                        errors.append(f"Prefix '{prefix}' field '{field_name}' allowed values list must be a list")
                    else:
                        assigned = set()
                        assignment_rules = field_conf.get("assignment_rules", [])
                        if isinstance(assignment_rules, list):
                            for rule in assignment_rules:
                                if isinstance(rule, dict) and "value" in rule:
                                    assigned.add(rule["value"])

                        unused_values = [
                            val for val in allowed_values
                            if val != default_val and val not in assigned
                        ]
                        if unused_values:
                            warnings.append(
                                f"Prefix '{prefix}' field '{field_name}': Values that are defined but not used: {unused_values}"
                            )

                # Dependency rules referential integrity
                rules = field_conf.get("rules", [])
                if rules:
                    if not isinstance(rules, list):
                        errors.append(f"Prefix '{prefix}' field '{field_name}' rules must be a list")
                    else:
                        for idx, rule in enumerate(rules):
                            if not isinstance(rule, dict):
                                errors.append(f"Prefix '{prefix}' field '{field_name}' rule at index {idx} must be a JSON object")
                                continue
                            rule_type = rule.get("rule_type", "dependency_check")
                            if rule_type == "package_restriction":
                                source = rule.get("source")
                                blocklist = rule.get("blocklist")
                                if not source or blocklist is None:
                                    errors.append(f"Prefix '{prefix}' field '{field_name}' rule at index {idx} must specify both 'source' and 'blocklist'")
                                    continue
                                if allowed_values is not None and source not in allowed_values:
                                    errors.append(f"Prefix '{prefix}' field '{field_name}' rule source '{source}' is not in allowed values list {allowed_values}")
                            elif rule_type == "naming_convention":
                                classification = rule.get("classification")
                                suffix = rule.get("name_suffix")
                                prefix_pattern = rule.get("name_prefix")
                                if not classification or (not suffix and not prefix_pattern):
                                    errors.append(f"Prefix '{prefix}' field '{field_name}' rule at index {idx} must specify 'classification' and at least one of 'name_suffix' or 'name_prefix'")
                                    continue
                                if allowed_values is not None and classification not in allowed_values:
                                    errors.append(f"Prefix '{prefix}' field '{field_name}' rule classification '{classification}' is not in allowed values list {allowed_values}")
                            else:
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

                # Propagation barriers referential integrity
                barriers = field_conf.get("barriers", [])
                if barriers:
                    if not isinstance(barriers, list):
                        errors.append(f"Prefix '{prefix}' field '{field_name}' barriers must be a list")
                    else:
                        barrier_field_name = FieldConfig.from_dict(field_name, field_conf).barrier_field
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

        return {"success": len(errors) == 0, "errors": errors, "warnings": warnings}

    @classmethod
    def parse_and_validate(cls, path: Union[str, Any]) -> Tuple[Optional["ArchConfig"], Dict[str, Any]]:
        """Parses and validates the configuration from a project root or config file path.
        Returns a tuple (arch_config_or_none, validation_result_dict).
        """
        import json
        from pathlib import Path
        p = Path(path)
        if p.is_dir():
            target = p / ".arch" / "config.json"
        elif p.name == "config.json":
            target = p
        else:
            target = p

        if not target.exists():
            return None, {"success": False, "errors": [f"Configuration file not found at {target}"], "warnings": []}

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return None, {"success": False, "errors": [f"Failed to parse config.json as JSON: {e}"], "warnings": []}
        except Exception as e:
            return None, {"success": False, "errors": [f"Failed to read config.json: {e}"], "warnings": []}

        val_result = cls.validate_dict(data)
        if not val_result.get("success", False):
            return None, val_result

        return cls.from_dict(data), val_result

    @classmethod
    def find_applicable_prefix(cls, filepath: str, config: Union["ArchConfig", Dict[str, Any]]) -> Optional[str]:
        if isinstance(config, ArchConfig):
            return config.get_applicable_prefix(filepath)
        prefixes = config.get("prefixes", config) if isinstance(config, dict) else {}
        normalized_path = filepath.replace("\\", "/")
        matching = None
        for prefix in prefixes.keys():
            if prefix == ".":
                if matching is None:
                    matching = "."
            elif normalized_path.startswith(prefix):
                if matching is None or len(prefix) > len(matching):
                    matching = prefix
        return matching

    @classmethod
    def find_applicable_config(cls, filepath: str, config: Union["ArchConfig", Dict[str, Any]]) -> Optional[Any]:
        if isinstance(config, ArchConfig):
            return config.get_applicable_config(filepath)
        prefix = cls.find_applicable_prefix(filepath, config)
        return config.get(prefix) if prefix and isinstance(config, dict) else None

    def get_applicable_prefix(
        self,
        filepath: str,
        config: Optional[Union["ArchConfig", Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """Resolves the most specific directory prefix matching the filepath."""
        if config is not None:
            prefixes = config.prefixes if isinstance(config, ArchConfig) else config
        else:
            prefixes = self.prefixes

        normalized_path = filepath.replace("\\", "/")
        matching_prefix = None
        for prefix in prefixes.keys():
            if prefix == ".":
                if matching_prefix is None:
                    matching_prefix = "."
            elif normalized_path.startswith(prefix):
                if matching_prefix is None or len(prefix) > len(matching_prefix):
                    matching_prefix = prefix
        return matching_prefix

    def get_applicable_config(
        self,
        filepath: str,
        config: Optional[Union["ArchConfig", Dict[str, Any]]] = None,
    ) -> Optional[Any]:
        """Resolves the most specific directory prefix configuration matching the filepath."""
        if config is not None:
            prefixes = config.prefixes if isinstance(config, ArchConfig) else config
        else:
            prefixes = self.prefixes

        matching_prefix = self.get_applicable_prefix(filepath, prefixes)
        return prefixes.get(matching_prefix) if matching_prefix else None

    def get(self, key: str, default: Any = None) -> Any:
        return self.prefixes.get(key, default)

    def keys(self):
        return self.prefixes.keys()

    def values(self):
        return self.prefixes.values()

    def items(self):
        return self.prefixes.items()

    def __iter__(self) -> Iterator[str]:
        return iter(self.prefixes)

    def __len__(self) -> int:
        return len(self.prefixes)

    def __bool__(self) -> bool:
        return bool(self.prefixes)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.exclude:
            result["exclude"] = list(self.exclude)
        for name, prefix_conf in self.prefixes.items():
            result[name] = prefix_conf.to_dict()
        result.update(self.extra)
        return result
