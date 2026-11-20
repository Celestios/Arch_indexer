from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.path_tracer import PathTracer
from utils.helpers import matches_filter, find_definition_line
from utils.violation_id import ViolationId


class NamingViolationChecker:
    """Checks naming conventions for architectural boundary compliance."""

    def __init__(self, repository: Repository, tracer: PathTracer):
        self.repository = repository
        self.tracer = tracer

    def check(self, repository, symbol_classifications: Dict, all_edges: List[Dict],
              config: Dict, filepath_filter: Optional[str],
              propagation_sources: Dict) -> List[Dict[str, Any]]:
        violations = []
        naming_rules = []
        for prefix, prefix_conf in config.items():
            rules = prefix_conf.get("rules", [])
            for r in rules:
                if r.get("rule_type") == "naming_convention":
                    naming_rules.append((prefix, r))
            auto_fields = prefix_conf.get("automatic_fields", {})
            for field_name, field_conf in auto_fields.items():
                for r in field_conf.get("rules", []):
                    if r.get("rule_type") == "naming_convention":
                        naming_rules.append((prefix, r))

        for sym, data in symbol_classifications.items():
            filepath = data["symbol_info"]["filepath"]
            if not filepath:
                continue
            if not matches_filter(filepath, filepath_filter):
                continue

            for prefix, rule in naming_rules:
                if filepath.replace("\\", "/").startswith(prefix):
                    classification = rule.get("classification")
                    suffix = rule.get("name_suffix")
                    prefix_pattern = rule.get("name_prefix")
                    is_match = any(f_val == classification for f_val in data["fields"].values())
                    if not is_match:
                        continue
                    simple_name = self.tracer.get_simple_name(sym)
                    violated = (suffix and not simple_name.endswith(suffix)) or (prefix_pattern and not simple_name.startswith(prefix_pattern))
                    if not violated:
                        continue
                    msg = rule.get("message", f"Naming convention violation: '{simple_name}' must match constraints for {classification}")
                    line_number = find_definition_line(self.repository, sym, filepath)
                    violation_id = ViolationId.generate(sym, "naming", classification)
                    rule_id = f"naming_{classification}".lower().replace("/", "_").replace(".", "_")
                    vdata = {"violation_id": violation_id, "rule_id": rule_id, "symbol": sym,
                             "filepath": filepath, "line": line_number, "message": msg, "origin": "automatic"}
                    violations.append(vdata)
        return violations
