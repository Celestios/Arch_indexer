from typing import Dict, List, Any, Optional
from auditor.path_tracer import PathTracer
from utils.helpers import matches_filter
from utils.violation_id import ViolationId
from auditor.snapshot import AuditSnapshot


def check(
    snapshot: AuditSnapshot,
    symbol_classifications: Dict[str, Any],
    propagation_sources: Dict[str, Any],
    config: Any,
    filepath_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Checks naming conventions for architectural boundary compliance."""
    violations = []
    if not config:
        return violations

    tracer = PathTracer()
    naming_rules = []
    for prefix, prefix_conf in config.items():
        rules = prefix_conf.get("rules", [])
        for r in rules:
            if r.get("rule_type") == "naming_convention":
                naming_rules.append((prefix, r, None))
        auto_fields = prefix_conf.get("automatic_fields", {})
        for field_name, field_conf in auto_fields.items():
            for r in field_conf.get("rules", []):
                if r.get("rule_type") == "naming_convention":
                    naming_rules.append((prefix, r, field_name))

    for sym, data in (symbol_classifications or {}).items():
        filepath = data["symbol_info"]["filepath"]
        if not filepath:
            continue
        if not matches_filter(filepath, filepath_filter):
            continue

        for prefix, rule, field_name in naming_rules:
            if filepath.replace("\\", "/").startswith(prefix):
                classification = rule.get("classification")
                suffix = rule.get("name_suffix")
                prefix_pattern = rule.get("name_prefix")
                is_match = any(f_val == classification for f_val in data["fields"].values())
                if not is_match:
                    continue
                simple_name = tracer.get_simple_name(sym)
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
                    def_info = snapshot.definitions_by_symbol.get(sym)
                    if def_info:
                        line_number = def_info.get("start_line")
                    if line_number is None and sym in snapshot.symbol_map:
                        line_number = snapshot.symbol_map[sym].get("start_line")
                if line_number is None:
                    line_number = 1

                violation_id = ViolationId.generate(sym, "naming", classification)
                rule_id = f"naming_{classification}".lower().replace("/", "_").replace(".", "_")
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
