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
    def parse_and_validate(cls, path: Union[str, Any]) -> Tuple[Optional["ArchConfig"], Dict[str, Any]]:
        """Parses and validates the configuration from a project root or config file path.
        Returns a tuple (arch_config_or_none, validation_result_dict).
        """
        import json
        from pathlib import Path
        p = Path(path)
        if p.is_dir():
            target = p / ".arch" / "config.json"
            root = p
        elif p.name == "config.json":
            target = p
            root = p.parent.parent if p.parent.name == ".arch" else p.parent
        else:
            target = p
            root = p.parent

        from auditor.validator import ConfigValidator
        validator = ConfigValidator(root)
        validator.config_path = target
        val_result = validator.validate()

        if not val_result.get("success", False):
            return None, val_result

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data), val_result
        except Exception as e:
            return None, {"success": False, "errors": [str(e)], "warnings": []}

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
