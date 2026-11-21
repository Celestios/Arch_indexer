from typing import Dict, List, Any, Optional
from auditor.path_tracer import get_simple_name
from auditor.snapshot import AuditSnapshot
from utils.arch_config import ArchConfig, build_rule_id
from utils.helpers import matches_filter
from utils.violation_id import generate_violation_id


def check(
    snapshot: AuditSnapshot,
    symbol_classifications: Dict[str, Any],
    propagation_sources: Dict[str, Any],
    config: Any,
    filepath_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Checks naming conventions for architectural boundary compliance."""
    violations: List[Dict[str, Any]] = []
    if not config:
        return violations

    cfg = config if isinstance(config, ArchConfig) else ArchConfig.from_dict(config)

    naming_rules = []
    for prefix, prefix_conf in cfg.items():
        for r in prefix_conf.rules:
            if r.get("rule_type") == "naming_convention":
                naming_rules.append((prefix, r, None))
        for field_name, field_conf in prefix_conf.automatic_fields.items():
            for r in field_conf.get("rules", []):
                if r.get("rule_type") == "naming_convention":
                    naming_rules.append((prefix, r, field_name))

    for sym, data in (symbol_classifications or {}).items():
        filepath = data["symbol_info"]["filepath"]
        if not filepath or not matches_filter(filepath, filepath_filter):
            continue

        norm_fp = filepath.replace("\\", "/")
        for prefix, rule, field_name in naming_rules:
            if prefix == "." or norm_fp.startswith(prefix):
                classification = rule.get("classification")
                suffix = rule.get("name_suffix")
                prefix_pattern = rule.get("name_prefix")
                if not any(f_val == classification for f_val in data["fields"].values()):
                    continue
                simple_name = get_simple_name(sym)
                violated = (suffix and not simple_name.endswith(suffix)) or (
                    prefix_pattern and not simple_name.startswith(prefix_pattern)
                )
                if not violated:
                    continue

                msg = rule.get(
                    "message",
                    f"Naming convention violation: '{simple_name}' must match constraints for {classification}",
                )
                line_number = None
                if snapshot is not None:
                    def_info = snapshot.get_definition(sym)
                    if def_info:
                        line_number = def_info.get("start_line")
                    if line_number is None:
                        sym_info = snapshot.get_symbol(sym)
                        if sym_info:
                            line_number = sym_info.get("start_line")
                if line_number is None:
                    line_number = 1

                violation_id = generate_violation_id(sym, "naming", classification)
                rule_id = build_rule_id(prefix, field_name, "naming_convention", classification=classification)
                violations.append({
                    "violation_id": violation_id,
                    "rule_id": rule_id,
                    "symbol": sym,
                    "filepath": filepath,
                    "line": line_number,
                    "message": msg,
                    "origin": "automatic",
                })
    return violations
