import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.classifier import SymbolClassifier
from auditor.propagation import MetadataPropagator
from auditor.path_tracer import PathTracer
from auditor.config_loader import ConfigLoader
from auditor.field_validator import FieldValidator
from auditor.edge_weights import EdgeWeightUpdater
from utils.helpers import matches_filter, find_definition_line, config_path_for, load_config
from utils.violation_id import ViolationId


class Auditor:
    """
    Evaluates workspace architectural boundary compliance rules.
    Loads configurations from .arch/config.json and audits symbols/edges inside the database.
    Delegates tasks to classifier, propagator, and path tracer modules.
    """

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root
        self.config_path = config_path_for(project_root)

        self.config_loader = ConfigLoader(self.config_path)
        self.classifier = SymbolClassifier(repository)
        self.propagator = MetadataPropagator()
        self.tracer = PathTracer(repository)
        self.field_validator = FieldValidator(repository, self.config_loader)
        self.edge_weight_updater = EdgeWeightUpdater(repository)

    def load_config(self) -> Dict[str, Any]:
        """Loads the workspace architectural configuration."""
        return load_config(self.project_root)

    def run_audit(self, filepath_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Runs the architectural compliance audit.
        Resolves symbols classifications, checks dependency rules, and saves violations.
        If filepath_filter is provided, only audits files matching that path prefix.
        """
        config = self.config_loader.load_config()
        if not config:
            print("No architectural rules found in .arch/config.json. Skipping audit.")
            return []

        self._clear_old_violations(filepath_filter)
        self.field_validator.reset_invalid_manual_fields(config)
        self._handle_config_change()

        all_symbols = self._fetch_all_symbols()
        outgoing_map = self._build_outgoing_map(all_symbols)
        symbol_classifications = self._classify_symbols(all_symbols, outgoing_map, config)
        all_edges = self._fetch_all_edges()

        propagation_sources = self.propagator.run_propagation(symbol_classifications, all_edges, config)
        self.edge_weight_updater.update_edge_weights(all_edges, symbol_classifications, config)

        violations = []
        violations.extend(self._check_dependency_violations(symbol_classifications, all_edges, config, filepath_filter, propagation_sources))
        violations.extend(self._check_naming_violations(symbol_classifications, config, filepath_filter))
        violations.extend(self._check_pending_audits(filepath_filter))

        self._recompute_file_statuses(violations)
        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.")
        return violations

    def _clear_old_violations(self, filepath_filter: Optional[str]):
        if filepath_filter:
            self.repository.compliance.delete_automatic_violations_for_path(filepath_filter)
        else:
            self.repository.compliance.delete_automatic_violations()

    def _handle_config_change(self):
        from change_tracker.tracker import ChangeTracker
        config_changed = ChangeTracker.check_config_changed(self.project_root, self.repository)
        if config_changed:
            ChangeTracker.update_config_hash(self.project_root, self.repository)

    def _fetch_all_symbols(self) -> List[Dict[str, Any]]:
        return self.repository.symbols.get_all_symbols_with_metadata()

    def _build_outgoing_map(self, all_symbols: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        outgoing_calls_map = {}
        for sym in all_symbols:
            outgoing = self.repository.edges.get_outgoing_edges(sym["symbol"])
            outgoing_calls_map[sym["symbol"]] = [o["target"] for o in outgoing]
        return outgoing_calls_map

    def _classify_symbols(self, all_symbols, outgoing_map, config) -> Dict[str, Dict[str, Any]]:
        file_metadata = self.repository.files.get_all_files_metadata()
        symbol_classifications = {}
        for sym in all_symbols:
            filepath = sym.get("filepath")
            if not filepath:
                continue
            prefix_conf = self.config_loader.get_applicable_config(filepath, config)
            if not prefix_conf:
                continue
            outgoing = outgoing_map.get(sym["symbol"], [])
            classifications = self.classifier.assign_automatic_fields(sym, prefix_conf, outgoing)
            if filepath in file_metadata:
                manual_fields = file_metadata[filepath].get("manual_fields") or {}
                classifications.update(manual_fields)
            symbol_classifications[sym["symbol"]] = {
                "symbol_info": sym, "fields": classifications,
                "static_fields": dict(classifications), "prefix_conf": prefix_conf
            }
        return symbol_classifications

    def _fetch_all_edges(self) -> List[Dict[str, Any]]:
        return self.repository.edges.get_all_edges_with_relation()

    def _check_dependency_violations(self, symbol_classifications, all_edges, config, filepath_filter, propagation_sources) -> List[Dict[str, Any]]:
        violations = []
        for edge in all_edges:
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
                        v = self._check_single_dependency(rule, source_sym, target_sym, source_data, target_data, filepath, field_name, config, propagation_sources, field_conf)
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
        line_number = find_definition_line(self.repository, target_sym, filepath)
        violation_id = ViolationId.generate(source_sym, target_sym, "pkg_restrict", forbidden_source)
        rule_id = f"{field_name}_pkg_{forbidden_source}".lower().replace("/", "_").replace(".", "_")
        data = {"violation_id": violation_id, "rule_id": rule_id, "symbol": source_sym,
                "filepath": filepath, "line": line_number, "message": msg, "origin": "automatic"}
        self.repository.compliance.add_violation(**data)
        return [data]

    def _check_single_dependency(self, rule, source_sym, target_sym, source_data, target_data, filepath, field_name, config, propagation_sources, field_conf) -> Optional[Dict[str, Any]]:
        source_val = source_data["static_fields"].get(field_name)
        target_val = target_data["fields"].get(field_name)
        if source_val is None or target_val is None:
            return None
        forbidden_source, forbidden_target = rule.get("source"), rule.get("target")
        if source_val != forbidden_source or target_val != forbidden_target:
            return None

        msg = rule.get("message", f"Dependency violation: {source_val} is not allowed to call {target_val}")
        path = self._trace_propagation_path(source_sym, target_sym, field_name, propagation_sources, field_conf)
        trace_msg = msg + self.tracer.format_path_trace(path)
        line_number = find_definition_line(self.repository, target_sym, filepath)

        violation_id = ViolationId.generate(source_sym, target_sym, field_name, forbidden_source, forbidden_target)
        rule_id = f"{field_name}_{forbidden_source}_{forbidden_target}".lower().replace("/", "_").replace(".", "_")
        matched_prefix = None
        for prefix in config.keys():
            if filepath.replace("\\", "/").startswith(prefix):
                if matched_prefix is None or len(prefix) > len(matched_prefix):
                    matched_prefix = prefix
        if matched_prefix:
            rule_id = f"{matched_prefix}_{rule_id}".lower().replace("/", "_").replace(".", "_")

        data = {"violation_id": violation_id, "rule_id": rule_id, "symbol": source_sym,
                "filepath": filepath, "line": line_number, "message": trace_msg, "origin": "automatic"}
        self.repository.compliance.add_violation(**data)
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

    def _check_naming_violations(self, symbol_classifications, config, filepath_filter) -> List[Dict[str, Any]]:
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
                    self.repository.compliance.add_violation(**vdata)
        return violations

    def _check_pending_audits(self, filepath_filter) -> List[Dict[str, Any]]:
        violations = []
        file_metadata = self.repository.files.get_all_files_metadata()
        for f_path, meta in file_metadata.items():
            if not meta.get("pending_audit"):
                continue
            if not matches_filter(f_path, filepath_filter):
                continue
            justification_msg = meta.get("justification") or ""
            msg = f"{f_path}: file changed" if "modified" in justification_msg.lower() or "changed" in justification_msg.lower() else f"{f_path}: new file"
            violation_id = ViolationId.generate("pending_audit", f_path)
            vdata = {"violation_id": violation_id, "rule_id": "pending_audit", "symbol": None,
                     "filepath": f_path, "line": 1, "message": msg, "origin": "automatic"}
            violations.append(vdata)
            self.repository.compliance.add_violation(**vdata)
        return violations

    def _recompute_file_statuses(self, violations):
        file_metadata = self.repository.files.get_all_files_metadata()
        violations_by_file = {}
        for v in violations:
            violations_by_file.setdefault(v["filepath"], []).append(v.get("origin", "automatic"))
        for f_path in file_metadata.keys():
            v_origins = violations_by_file.get(f_path, [])
            new_status = "COMPLIANT" if not v_origins or all(o != "automatic" for o in v_origins) else "VIOLATION_DETECTED"
            self.repository.files.update_file_status(f_path, new_status)
