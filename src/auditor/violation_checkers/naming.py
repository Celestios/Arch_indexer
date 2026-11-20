from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.path_tracer import PathTracer
from utils.helpers import matches_filter, find_definition_line
from utils.violation_id import ViolationId


class NamingViolationChecker:
    """Checks naming conventions for architectural boundary compliance."""

    def __init__(self, repository: Optional[Repository] = None, tracer: Optional[PathTracer] = None):
        self.repository = repository
        self.tracer = tracer or PathTracer(repository)

    def check(
        self,
        snapshot: Any,
        symbol_classifications: Any = None,
        config: Any = None,
        filepath_filter: Optional[str] = None,
        propagation_sources: Optional[Dict] = None,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        from auditor.snapshot import AuditSnapshot

        if isinstance(snapshot, AuditSnapshot):
            snap = snapshot
            classifications = symbol_classifications or {}
            cfg = config
            fp_filter = filepath_filter
        else:
            classifications = snapshot
            cfg = config
            fp_filter = filepath_filter
            snap = kwargs.get("snapshot")

        violations = []
        if not cfg:
            return violations
        naming_rules = []
        for prefix, prefix_conf in cfg.items():
            rules = prefix_conf.get("rules", [])
            for r in rules:
                if r.get("rule_type") == "naming_convention":
                    naming_rules.append((prefix, r))
            auto_fields = prefix_conf.get("automatic_fields", {})
            for field_name, field_conf in auto_fields.items():
                for r in field_conf.get("rules", []):
                    if r.get("rule_type") == "naming_convention":
                        naming_rules.append((prefix, r))

        for sym, data in classifications.items():
            filepath = data["symbol_info"]["filepath"]
            if not filepath:
                continue
            if not matches_filter(filepath, fp_filter):
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
                    line_number = None
                    if snap is not None:
                        def_info = snap.definitions_by_symbol.get(sym)
                        if def_info:
                            line_number = def_info.get("start_line")
                        if line_number is None and sym in snap.symbol_map:
                            line_number = snap.symbol_map[sym].get("start_line")
                    if line_number is None and self.repository:
                        line_number = find_definition_line(self.repository, sym, filepath)
                    if line_number is None:
                        line_number = 1
                    violation_id = ViolationId.generate(sym, "naming", classification)
                    rule_id = f"naming_{classification}".lower().replace("/", "_").replace(".", "_")
                    vdata = {"violation_id": violation_id, "rule_id": rule_id, "symbol": sym,
                             "filepath": filepath, "line": line_number, "message": msg, "origin": "automatic"}
                    violations.append(vdata)
        return violations
