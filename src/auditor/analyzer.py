import json
import sys
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.classifier import SymbolClassifier
from auditor.propagation import MetadataPropagator
from auditor.path_tracer import PathTracer

class Auditor:
    """
    Evaluates workspace architectural boundary compliance rules.
    Loads configurations from .arch/config.json and audits symbols/edges inside the database.
    Delegates tasks to classifier, propagator, and path tracer modules.
    """

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root
        self.config_path = project_root / ".arch" / "config.json"
        
        self.classifier = SymbolClassifier(repository)
        self.propagator = MetadataPropagator()
        self.tracer = PathTracer(repository)

    def load_config(self) -> Dict[str, Any]:
        """Loads and parses the .arch/config.json file."""
        if not self.config_path.exists():
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            return {}

    def get_applicable_config(self, filepath: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Resolves the most specific directory prefix configuration matching the filepath.
        Longest matching prefix wins. '.' is used for root-level files.
        """
        # Convert path separators to forward slashes for matching
        normalized_path = filepath.replace("\\", "/")
        
        matching_prefix = None
        for prefix in config.keys():
            if prefix == ".":
                if matching_prefix is None:
                    matching_prefix = "."
            elif normalized_path.startswith(prefix):
                if matching_prefix is None or len(prefix) > len(matching_prefix):
                    matching_prefix = prefix
                    
        return config.get(matching_prefix) if matching_prefix else None

    def run_audit(self, filepath_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Runs the architectural compliance audit.
        Resolves symbols classifications, checks dependency rules, and saves violations.
        If filepath_filter is provided, only audits files matching that path prefix.
        """
        config = self.load_config()
        if not config:
            print("No architectural rules found in .arch/config.json. Skipping audit.")
            return []

        self._clear_old_violations(filepath_filter)
        self._reset_invalid_manual_fields(config)
        self._handle_config_change()

        all_symbols = self._fetch_all_symbols()
        outgoing_map = self._build_outgoing_map(all_symbols)
        symbol_classifications = self._classify_symbols(all_symbols, outgoing_map, config)
        all_edges = self._fetch_all_edges()

        propagation_sources = self.propagator.run_propagation(symbol_classifications, all_edges, config)
        self._update_edge_weights(all_edges, symbol_classifications, config)

        violations = []
        violations.extend(self._check_dependency_violations(symbol_classifications, all_edges, config, filepath_filter, propagation_sources))
        violations.extend(self._check_naming_violations(symbol_classifications, config, filepath_filter))
        violations.extend(self._check_pending_audits(filepath_filter))

        self._recompute_file_statuses(violations)
        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.")
        return violations

    def _clear_old_violations(self, filepath_filter: Optional[str]):
        with self.repository.db_conn.session() as conn:
            if filepath_filter:
                normalized_filter = filepath_filter.replace("\\", "/")
                conn.execute(
                    "DELETE FROM compliance_violations WHERE replace(filepath, '\\', '/') LIKE ? AND origin = 'automatic'",
                    (f"{normalized_filter}%",)
                )
            else:
                conn.execute("DELETE FROM compliance_violations WHERE origin = 'automatic'")

    def _reset_invalid_manual_fields(self, config: Dict[str, Any]):
        from change_tracker.tracker import ChangeTracker
        file_metadata = self.repository.files.get_all_files_metadata()
        db_updated = False

        for filepath, meta in file_metadata.items():
            prefix_conf = self.get_applicable_config(filepath, config)
            if not prefix_conf:
                continue

            manual_cfg = prefix_conf.get("manual_fields", {})
            current_manual_fields = meta.get("manual_fields") or {}
            updated_fields = dict(current_manual_fields)
            fields_to_reset = []
            justification = meta.get("justification") or ""
            is_modified = (meta.get("pending_audit") and justification == "File modified, pending re-audit")
            fields_changed = False

            for field_name, field_conf in manual_cfg.items():
                default_val = field_conf.get("default")
                allowed_values = field_conf.get("values")
                reset_on_change = field_conf.get("reset_on_change", False)
                curr_val = current_manual_fields.get(field_name)

                if curr_val is not None and allowed_values is not None and curr_val not in allowed_values:
                    print(
                        f"warning: value '{curr_val}' for manual field '{field_name}' in '{filepath}' is no longer allowed. "
                        f"Resetting to default '{default_val}' and marking for audit.",
                        file=sys.stderr
                    )
                    updated_fields[field_name] = default_val
                    fields_changed = True
                    with self.repository.db_conn.session() as conn:
                        conn.execute(
                            "UPDATE files SET pending_audit = TRUE, justification = ? WHERE filepath = ?",
                            (f"Manual field '{field_name}' value '{curr_val}' not allowed by config, reset to default.", filepath)
                        )
                    db_updated = True
                elif is_modified and reset_on_change:
                    if curr_val != default_val:
                        updated_fields[field_name] = default_val
                        fields_changed = True
                        fields_to_reset.append(field_name)

            if fields_changed:
                if is_modified and fields_to_reset:
                    reset_msg = ", ".join(fields_to_reset)
                    new_justification = f"File modified, pending re-audit (fields reset: {reset_msg})"
                    self.repository.files.update_file_manual_fields(filepath, updated_fields, new_justification)
                else:
                    self.repository.files.update_file_manual_fields(filepath, updated_fields, justification)
                db_updated = True

        if db_updated:
            self.repository.files.get_all_files_metadata()

    def _handle_config_change(self):
        from change_tracker.tracker import ChangeTracker
        config_changed = ChangeTracker.check_config_changed(self.project_root, self.repository)
        if config_changed:
            ChangeTracker.update_config_hash(self.project_root, self.repository)

    def _fetch_all_symbols(self) -> List[Dict[str, Any]]:
        all_symbols = []
        with self.repository.db_conn.session() as conn:
            res = conn.execute("SELECT symbol, filepath, kind, signature, docstring FROM symbols").fetchall()
            for r in res:
                all_symbols.append({
                    "symbol": r[0], "filepath": r[1], "kind": r[2],
                    "signature": r[3], "docstring": r[4]
                })
        return all_symbols

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
            prefix_conf = self.get_applicable_config(filepath, config)
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
        with self.repository.db_conn.session() as conn:
            res = conn.execute("SELECT source, target, relation FROM edges").fetchall()
            return [{"source": r[0], "target": r[1], "relation": r[2]} for r in res]

    def _update_edge_weights(self, all_edges, symbol_classifications, config):
        all_barriers = set()
        for prefix, prefix_conf in config.items():
            auto_fields = prefix_conf.get("automatic_fields", {})
            manual_fields = prefix_conf.get("manual_fields", {})
            for field_name, field_conf in {**auto_fields, **manual_fields}.items():
                if field_conf.get("handler") == "propagation":
                    all_barriers.update(field_conf.get("barriers") or [])

        updated_edges = []
        for edge in all_edges:
            src, tgt, rel = edge["source"], edge["target"], edge["relation"]
            weight = 1.0
            src_data = symbol_classifications.get(src)
            tgt_data = symbol_classifications.get(tgt)
            if src_data:
                src_layer = src_data["fields"].get("layer")
                tgt_layer = tgt_data["fields"].get("layer") if tgt_data else None
                if src_layer and tgt_layer and src_layer == tgt_layer:
                    weight *= 1.5
                src_tier = src_data["fields"].get("tier")
                tgt_tier = tgt_data["fields"].get("tier") if tgt_data else None
                if src_tier is not None and tgt_tier is not None:
                    try:
                        if int(src_tier) > int(tgt_tier):
                            weight *= 0.5
                    except ValueError:
                        pass
                src_role = src_data["fields"].get("architectural_role") or src_data["fields"].get("role") or ""
                if src_role in all_barriers:
                    weight *= 0.3
            updated_edges.append((weight, src, tgt, rel))

        if updated_edges:
            with self.repository.db_conn.session() as conn:
                conn.executemany(
                    "UPDATE edges SET weight = ? WHERE source = ? AND target = ? AND relation = ?",
                    updated_edges
                )

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
            if filepath_filter:
                norm_source_fp = filepath.replace("\\", "/")
                norm_filter = filepath_filter.replace("\\", "/")
                if not norm_source_fp.startswith(norm_filter):
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
        line_number = self.repository.symbols.get_occurrences_for_symbol(target_sym)
        line_number = next((occ["start_line"] for occ in line_number if occ["filepath"] == filepath), 1)
        from utils.helpers import ViolationId
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
        line_number = next((occ["start_line"] for occ in self.repository.symbols.get_occurrences_for_symbol(target_sym) if occ["filepath"] == filepath), 1)

        from utils.helpers import ViolationId
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
            if filepath_filter:
                norm_source_fp = filepath.replace("\\", "/")
                norm_filter = filepath_filter.replace("\\", "/")
                if not norm_source_fp.startswith(norm_filter):
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
                    line_number = next((occ["start_line"] for occ in self.repository.symbols.get_occurrences_for_symbol(sym) if occ["filepath"] == filepath and occ["role"] == 1), 1)
                    if line_number == 1:
                        occs = self.repository.symbols.get_occurrences_for_symbol(sym)
                        if occs:
                            line_number = occs[0]["start_line"]
                    from utils.helpers import ViolationId
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
            if filepath_filter:
                norm_source_fp = f_path.replace("\\", "/")
                norm_filter = filepath_filter.replace("\\", "/")
                if not norm_source_fp.startswith(norm_filter):
                    continue
            justification_msg = meta.get("justification") or ""
            msg = f"{f_path}: file changed" if "modified" in justification_msg.lower() or "changed" in justification_msg.lower() else f"{f_path}: new file"
            from utils.helpers import ViolationId
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
