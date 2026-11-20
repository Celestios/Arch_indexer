from typing import Dict, List, Any, Optional, TYPE_CHECKING

from db.repository import Repository
from auditor.path_tracer import PathTracer
from auditor.config_loader import ConfigLoader
from auditor.violation_checkers.base import BaseViolationChecker
from utils.helpers import matches_filter, find_definition_line, find_call_site_or_definition_line
from utils.violation_id import ViolationId

if TYPE_CHECKING:
    from auditor.snapshot import AuditSnapshot


class DependencyViolationChecker(BaseViolationChecker):
    """Checks dependency rules for architectural boundary compliance."""

    def __init__(self, repository: Repository, tracer: PathTracer, config_loader: ConfigLoader):
        super().__init__(repository)
        self.tracer = tracer
        self.config_loader = config_loader

    def check(
        self,
        symbol_classifications: Any,
        all_edges: Any = None,
        config: Any = None,
        filepath_filter: Optional[str] = None,
        propagation_sources: Optional[Dict] = None,
        snapshot: Optional["AuditSnapshot"] = None
    ) -> List[Dict[str, Any]]:
        violations = []
        edges_to_check = all_edges or []
        for edge in edges_to_check:
            source_sym, target_sym = edge["source"], edge["target"]
            if source_sym not in symbol_classifications:
                continue
            source_data = symbol_classifications[source_sym]
            filepath = source_data["symbol_info"]["filepath"]
            if not filepath:
                continue
            if not matches_filter(filepath, filepath_filter):
                continue

            prefix_conf = source_data["prefix_conf"]
            auto_fields = prefix_conf.get("automatic_fields", {})

            for field_name, field_conf in auto_fields.items():
                rules = field_conf.get("rules", [])
                for rule in rules:
                    if rule.get("rule_type") == "package_restriction":
                        violations.extend(self._check_package_restriction(rule, source_sym, target_sym, source_data, filepath, field_name))
                    elif rule.get("rule_type", "dependency_check") == "dependency_check" and target_sym in symbol_classifications:
                        target_data = symbol_classifications[target_sym]
                        v = self._check_single_dependency(rule, source_sym, target_sym, source_data, target_data, filepath, field_name, config, propagation_sources, field_conf, symbol_classifications, snapshot=snapshot)
                        if v:
                            violations.append(v)
        return violations

    def _check_package_restriction(self, rule, source_sym, target_sym, source_data, filepath, field_name) -> List[Dict[str, Any]]:
        source_val = source_data["static_fields"].get(field_name)
        forbidden_source = rule.get("source")
        blocklist = rule.get("blocklist", [])
        if source_val != forbidden_source or not self.tracer.matches_blocklist(target_sym, blocklist):
            return []
        msg = rule.get("message", f"Package restriction violation: {source_val} cannot depend on {target_sym}")
        line_number = find_call_site_or_definition_line(self.repository, source_sym, target_sym, filepath)
        violation_id = ViolationId.generate(source_sym, target_sym, "pkg_restrict", forbidden_source)
        rule_id = f"{field_name}_pkg_{forbidden_source}".lower().replace("/", "_").replace(".", "_")
        data = {"violation_id": violation_id, "rule_id": rule_id, "symbol": source_sym,
                "filepath": filepath, "line": line_number, "message": msg, "origin": "automatic"}
        return [data]

    def _check_single_dependency(self, rule, source_sym, target_sym, source_data, target_data, filepath, field_name, config, propagation_sources, field_conf, symbol_classifications, snapshot: Optional["AuditSnapshot"] = None) -> Optional[Dict[str, Any]]:
        source_val = source_data["static_fields"].get(field_name)
        target_val = target_data["fields"].get(field_name)
        if source_val is None or target_val is None:
            return None
        forbidden_source, forbidden_target = rule.get("source"), rule.get("target")
        if source_val != forbidden_source or target_val != forbidden_target:
            return None

        msg = rule.get("message", f"Dependency violation: {source_val} is not allowed to call {target_val}")
        path = self._trace_propagation_path(source_sym, target_sym, field_name, propagation_sources, field_conf)
        trace_msg = msg + self.tracer.format_path_trace(path, snapshot=snapshot)

        # Counterfactual fix suggestions: Find existing barrier intermediaries
        fix_hint = self._find_counterfactual_fix(target_sym, target_data, field_name, field_conf, symbol_classifications, snapshot=snapshot)
        if fix_hint:
            trace_msg += f"\n  Suggested Fix: {fix_hint}"
        line_number = find_call_site_or_definition_line(self.repository, source_sym, target_sym, filepath)

        violation_id = ViolationId.generate(source_sym, target_sym, field_name, forbidden_source, forbidden_target)
        rule_id = f"{field_name}_{forbidden_source}_{forbidden_target}".lower().replace("/", "_").replace(".", "_")
        matched_prefix = self.config_loader.get_applicable_prefix(filepath, config)
        if matched_prefix:
            rule_id = f"{matched_prefix}_{rule_id}".lower().replace("/", "_").replace(".", "_")

        data = {"violation_id": violation_id, "rule_id": rule_id, "symbol": source_sym,
                "filepath": filepath, "line": line_number, "message": trace_msg, "origin": "automatic"}
        return data

    def _trace_propagation_path(self, source_sym, target_sym, field_name, propagation_sources, field_conf) -> List[str]:
        curr_src = source_sym
        src_path = [curr_src]
        visited = {curr_src}
        while (curr_src, field_name) in propagation_sources:
            curr_src = propagation_sources[(curr_src, field_name)]
            if curr_src in visited:
                break
            visited.add(curr_src)
            src_path.append(curr_src)

        curr_tgt = target_sym
        tgt_path = [curr_tgt]
        visited = {curr_tgt}
        while (curr_tgt, field_name) in propagation_sources:
            curr_tgt = propagation_sources[(curr_tgt, field_name)]
            if curr_tgt in visited:
                break
            visited.add(curr_tgt)
            tgt_path.append(curr_tgt)

        direction = field_conf.get("propagation_direction", "upstream")
        if direction == "upstream":
            path = src_path
            if path[-1] != target_sym:
                path = path + tgt_path
        else:
            path = list(reversed(src_path)) + list(reversed(tgt_path))

        seen = set()
        return [node for node in path if node not in seen and not seen.add(node)]

    def _find_counterfactual_fix(self, target_sym: str, target_data: Dict, field_name: str, field_conf: Dict, symbol_classifications: Dict, snapshot: Optional["AuditSnapshot"] = None) -> Optional[str]:
        barriers = field_conf.get("barriers", [])
        if not barriers:
            return None
        barrier_field = field_conf.get("barrier_field", "architectural_role") or "architectural_role"

        if snapshot is not None:
            incoming = snapshot.get_incoming(target_sym)
        else:
            incoming = self.repository.edges.get_incoming_edges(target_sym)
        parent_sym = target_data.get("symbol_info", {}).get("parent_symbol")
        if parent_sym:
            if snapshot is not None:
                incoming = incoming + snapshot.get_incoming(parent_sym)
            else:
                incoming = incoming + self.repository.edges.get_incoming_edges(parent_sym)

        candidates = []
        from utils.helpers import demangle_scip_symbol
        seen_callers = set()
        for edge in incoming:
            caller = edge.get("source")
            if not caller or caller.startswith("local ") or caller in seen_callers or caller not in symbol_classifications:
                continue
            seen_callers.add(caller)
            caller_fields = symbol_classifications[caller]["fields"]
            caller_layer = caller_fields.get(barrier_field)
            if caller_layer in barriers:
                clean_caller = demangle_scip_symbol(caller)
                clean_target = demangle_scip_symbol(target_sym)
                candidates.append(f"`{clean_caller}` (in {caller_layer}) already calls `{clean_target}`")
                if len(candidates) >= 2:
                    break
        if candidates:
            return f"Delegate through existing barrier intermediary in {'/'.join(barriers)}: " + "; ".join(candidates)
        return None
