import os
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

        # Clear existing violations for the target range to avoid stale data
        with self.repository.db_conn.session() as conn:
            if filepath_filter:
                normalized_filter = filepath_filter.replace("\\", "/")
                conn.execute(
                    "DELETE FROM compliance_violations WHERE replace(filepath, '\\', '/') LIKE ? AND origin = 'automatic'",
                    (f"{normalized_filter}%",)
                )
            else:
                conn.execute("DELETE FROM compliance_violations WHERE origin = 'automatic'")

        # 1. Fetch all symbols from the database
        all_symbols = []
        with self.repository.db_conn.session() as conn:
            res = conn.execute("SELECT symbol, filepath, kind, signature, docstring FROM symbols").fetchall()
            for r in res:
                all_symbols.append({
                    "symbol": r[0],
                    "filepath": r[1],
                    "kind": r[2],
                    "signature": r[3],
                    "docstring": r[4]
                })

        # 2. Map outgoing edges for callers
        outgoing_calls_map = {}
        for sym in all_symbols:
            outgoing = self.repository.edges.get_outgoing_edges(sym["symbol"])
            outgoing_calls_map[sym["symbol"]] = [o["target"] for o in outgoing]

        # 3. Classify all symbols dynamically
        file_metadata = self.repository.files.get_all_files_metadata()

        symbol_classifications = {}
        for sym in all_symbols:
            filepath = sym.get("filepath")
            if not filepath:
                continue  # Skip external third-party symbols for classification
                
            prefix_conf = self.get_applicable_config(filepath, config)
            if not prefix_conf:
                continue

            outgoing = outgoing_calls_map.get(sym["symbol"], [])
            classifications = self.classifier.assign_automatic_fields(sym, prefix_conf, outgoing)
            
            # Merge manual fields from files metadata (taking precedence)
            if filepath in file_metadata:
                manual_fields = file_metadata[filepath].get("manual_fields") or {}
                classifications.update(manual_fields)

            symbol_classifications[sym["symbol"]] = {
                "symbol_info": sym,
                "fields": classifications,
                "static_fields": dict(classifications), # Save static classifications
                "prefix_conf": prefix_conf
            }

        # Fetch all edges in the database
        all_edges = []
        with self.repository.db_conn.session() as conn:
            res = conn.execute("SELECT source, target, relation FROM edges").fetchall()
            all_edges = [{"source": r[0], "target": r[1], "relation": r[2]} for r in res]

        # 4. Run Graph-based Metadata Propagation
        propagation_sources = self.propagator.run_propagation(symbol_classifications, all_edges, config)

        # 5. Audit call graph edges for compliance violations
        violations = []
        
        # 5a. Dependency Checks & Package Restrictions
        for edge in all_edges:
            source_sym = edge["source"]
            target_sym = edge["target"]
            
            # We only audit edges where caller is classified
            if source_sym not in symbol_classifications:
                continue
                
            source_data = symbol_classifications[source_sym]
            filepath = source_data["symbol_info"]["filepath"]
            if not filepath:
                continue

            # Filter by filepath prefix if requested
            if filepath_filter:
                norm_source_fp = filepath.replace("\\", "/")
                norm_filter = filepath_filter.replace("\\", "/")
                if not norm_source_fp.startswith(norm_filter):
                    continue

            prefix_conf = source_data["prefix_conf"]
            auto_fields = prefix_conf.get("automatic_fields", {})
            
            for field_name, field_conf in auto_fields.items():
                rules = field_conf.get("rules", [])
                
                # Check package restriction rules
                for rule in rules:
                    if rule.get("rule_type") == "package_restriction":
                        source_val = source_data["static_fields"].get(field_name) # USE STATIC
                        forbidden_source = rule.get("source")
                        blocklist = rule.get("blocklist", [])
                        
                        if source_val == forbidden_source and self.tracer.matches_blocklist(target_sym, blocklist):
                            msg = rule.get("message", f"Package restriction violation: {source_val} cannot depend on {target_sym}")
                            
                            # Retrieve coordinate line number
                            line_number = 1
                            occs = self.repository.symbols.get_occurrences_for_symbol(target_sym)
                            for occ in occs:
                                if occ["filepath"] == filepath:
                                    line_number = occ["start_line"]
                                    break
                                    
                            violation_text = f"{source_sym}_{target_sym}_pkg_restrict_{forbidden_source}"
                            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                            rule_id = f"{field_name}_pkg_{forbidden_source}".lower().replace("/", "_").replace(".", "_")
                            
                            violation_data = {
                                "violation_id": violation_id,
                                "rule_id": rule_id,
                                "symbol": source_sym,
                                "filepath": filepath,
                                "line": line_number,
                                "message": msg,
                                "origin": "automatic"
                            }
                            violations.append(violation_data)
                            self.repository.compliance.add_violation(**violation_data)

                # Check standard dependency rules (only if target is classified)
                if target_sym in symbol_classifications:
                    target_data = symbol_classifications[target_sym]
                    
                    for rule in rules:
                        if rule.get("rule_type", "dependency_check") == "dependency_check":
                            source_val = source_data["static_fields"].get(field_name) # USE STATIC
                            target_val = target_data["fields"].get(field_name) # USE PROPAGATED
                            
                            if source_val is None or target_val is None:
                                continue
                                
                            forbidden_source = rule.get("source")
                            forbidden_target = rule.get("target")
                            
                            if source_val == forbidden_source and target_val == forbidden_target:
                                msg = rule.get("message", f"Dependency violation: {source_val} is not allowed to call {target_val}")
                                
                                # Trace the propagation path if either side was propagated
                                path = []
                                # Trace source side if it was propagated
                                curr_src = source_sym
                                src_path = [curr_src]
                                visited = {curr_src}
                                while (curr_src, field_name) in propagation_sources:
                                    curr_src = propagation_sources[(curr_src, field_name)]
                                    if curr_src in visited:
                                        break
                                    visited.add(curr_src)
                                    src_path.append(curr_src)
                                
                                # Trace target side if it was propagated
                                curr_tgt = target_sym
                                tgt_path = [curr_tgt]
                                visited = {curr_tgt}
                                while (curr_tgt, field_name) in propagation_sources:
                                    curr_tgt = propagation_sources[(curr_tgt, field_name)]
                                    if curr_tgt in visited:
                                        break
                                    visited.add(curr_tgt)
                                    tgt_path.append(curr_tgt)
                                
                                # Reconstruct path from caller source_path back to target_path root
                                direction = field_conf.get("propagation_direction", "upstream")
                                if direction == "upstream":
                                    path = src_path
                                    if path[-1] != target_sym:
                                        path = path + tgt_path
                                else:
                                    tgt_path_rev = list(reversed(tgt_path))
                                    src_path_rev = list(reversed(src_path))
                                    path = src_path_rev + tgt_path_rev
                                
                                # De-duplicate path while preserving order
                                seen = set()
                                final_path = []
                                for node in path:
                                    if node not in seen:
                                        final_path.append(node)
                                        seen.add(node)
                                
                                # Generate actionable trace message
                                trace_msg = msg + self.tracer.format_path_trace(final_path)
                                
                                # Retrieve coordinate line number
                                line_number = 1
                                occs = self.repository.symbols.get_occurrences_for_symbol(target_sym)
                                for occ in occs:
                                    if occ["filepath"] == filepath:
                                        line_number = occ["start_line"]
                                        break
                                        
                                violation_text = f"{source_sym}_{target_sym}_{field_name}_{forbidden_source}_{forbidden_target}"
                                violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                                
                                rule_id = f"{field_name}_{forbidden_source}_{forbidden_target}".lower().replace("/", "_").replace(".", "_")
                                matched_prefix = None
                                for prefix in config.keys():
                                    if filepath.replace("\\", "/").startswith(prefix):
                                        if matched_prefix is None or len(prefix) > len(matched_prefix):
                                            matched_prefix = prefix
                                if matched_prefix:
                                    rule_id = f"{matched_prefix}_{rule_id}".lower().replace("/", "_").replace(".", "_")
                                    
                                violation_data = {
                                    "violation_id": violation_id,
                                    "rule_id": rule_id,
                                    "symbol": source_sym,
                                    "filepath": filepath,
                                    "line": line_number,
                                    "message": trace_msg,
                                    "origin": "automatic"
                                }
                                violations.append(violation_data)
                                self.repository.compliance.add_violation(**violation_data)

        # 5b. Naming Convention Checks
        naming_rules = []
        for prefix, prefix_conf in config.items():
            rules = prefix_conf.get("rules", [])
            for r in rules:
                if r.get("rule_type") == "naming_convention":
                    naming_rules.append((prefix, r))
            
            auto_fields = prefix_conf.get("automatic_fields", {})
            for field_name, field_conf in auto_fields.items():
                rules = field_conf.get("rules", [])
                for r in rules:
                    if r.get("rule_type") == "naming_convention":
                        naming_rules.append((prefix, r))

        for sym, data in symbol_classifications.items():
            filepath = data["symbol_info"]["filepath"]
            if not filepath:
                continue
                
            # Filter by filepath prefix if requested
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
                    
                    # Check if symbol has this classification value in any of its fields
                    is_match = False
                    for f_name, f_val in data["fields"].items():
                        if f_val == classification:
                            is_match = True
                            break
                            
                    if is_match:
                        simple_name = self.tracer.get_simple_name(sym)
                        violated = False
                        if suffix and not simple_name.endswith(suffix):
                            violated = True
                        if prefix_pattern and not simple_name.startswith(prefix_pattern):
                            violated = True
                            
                        if violated:
                            msg = rule.get("message", f"Naming convention violation: '{simple_name}' must match constraints for {classification}")
                            
                            # Find definition line
                            line_number = 1
                            occs = self.repository.symbols.get_occurrences_for_symbol(sym)
                            for occ in occs:
                                if occ["filepath"] == filepath and occ["role"] == 1:
                                    line_number = occ["start_line"]
                                    break
                            if line_number == 1 and occs:
                                line_number = occs[0]["start_line"]
                                
                            violation_text = f"{sym}_naming_{classification}"
                            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                            rule_id = f"naming_{classification}".lower().replace("/", "_").replace(".", "_")
                            
                            violation_data = {
                                "violation_id": violation_id,
                                "rule_id": rule_id,
                                "symbol": sym,
                                "filepath": filepath,
                                "line": line_number,
                                "message": msg,
                                "origin": "automatic"
                            }
                            violations.append(violation_data)
                            self.repository.compliance.add_violation(**violation_data)

        # Re-compute automated status for all files based on active automatic violations
        violations_by_file = {}
        for v in violations:
            v_filepath = v["filepath"]
            violations_by_file.setdefault(v_filepath, []).append(v.get("origin", "automatic"))

        for f_path in file_metadata.keys():
            v_origins = violations_by_file.get(f_path, [])
            if not v_origins or all(o != "automatic" for o in v_origins):
                new_status = "COMPLIANT"
            else:
                new_status = "VIOLATION_DETECTED"
            self.repository.files.update_file_status(f_path, new_status)

        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.")
        return violations
