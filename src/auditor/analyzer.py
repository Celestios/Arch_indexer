import os
import json
import sys
import hashlib
import fnmatch
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from collections import deque
from db.connection import DbConnection
from db.repository import Repository

class Auditor:
    """
    Evaluates workspace architectural boundary compliance rules.
    Loads configurations from .arch/config.json and audits symbols/edges inside the DuckDB.
    """

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root
        self.config_path = project_root / ".arch" / "config.json"

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

    def evaluate_conditions(self, symbol_info: Dict[str, Any], conditions: Dict[str, Any], outgoing_targets: List[str]) -> bool:
        """
        Returns True if a symbol definition meets all the specified assignment conditions.
        """
        # 1. Path prefix matching
        if "path_prefix" in conditions:
            prefix = conditions["path_prefix"]
            filepath = symbol_info.get("filepath")
            if not filepath or not filepath.replace("\\", "/").startswith(prefix):
                return False
                
        # 2. Class name suffix matching
        symbol_name = symbol_info["symbol"].split(" ")[-1]  # Extract simple name from SCIP FQN
        if "class_suffix" in conditions:
            suffix = conditions["class_suffix"]
            if not symbol_name.endswith(suffix):
                return False

        # 3. Class name containing string matching
        if "class_contains" in conditions:
            substring = conditions["class_contains"]
            if substring not in symbol_name:
                return False

        # 4. Name containing matching
        if "name_contains" in conditions:
            substring = conditions["name_contains"]
            if substring not in symbol_name:
                return False

        # 5. Calls prefix matching (checks if symbol calls any symbol starting with the prefix)
        if "calls_prefix" in conditions:
            prefix = conditions["calls_prefix"]
            matched_call = False
            for target in outgoing_targets:
                # Resolve the target symbol details to check its file path
                target_node = self.repository.get_symbol(target)
                if target_node and target_node.get("filepath"):
                    if target_node["filepath"].replace("\\", "/").startswith(prefix):
                        matched_call = True
                        break
            if not matched_call:
                return False

        return True

    def assign_automatic_fields(
        self,
        symbol_info: Dict[str, Any],
        prefix_conf: Dict[str, Any],
        outgoing_targets: List[str]
    ) -> Dict[str, Any]:
        """
        Evaluates the prefix configuration's automatic fields and returns the assigned values.
        """
        assigned_values = {}
        auto_fields = prefix_conf.get("automatic_fields", {})
        
        for field_name, field_conf in auto_fields.items():
            default_val = field_conf.get("default")
            assigned_val = default_val
            
            # Check assignment rules in order (first match wins)
            assignment_rules = field_conf.get("assignment_rules", [])
            for rule in assignment_rules:
                target_value = rule.get("value")
                conditions = rule.get("conditions", {})
                
                if self.evaluate_conditions(symbol_info, conditions, outgoing_targets):
                    assigned_val = target_value
                    break
                    
            assigned_values[field_name] = assigned_val
            
        return assigned_values

    def _get_simple_name(self, symbol: str) -> str:
        """Extracts the simple class or function name from a SCIP FQN."""
        sym = symbol.strip()
        for separator in [" ", "::", ".", "/"]:
            if separator in sym:
                sym = sym.split(separator)[-1]
        return sym

    def _format_path_trace(self, path: List[str]) -> str:
        """Generates a formatted, line-numbered path trace from source to target."""
        trace_lines = []
        for i, sym in enumerate(path):
            symbol_info = self.repository.get_symbol(sym)
            filepath = symbol_info.get("filepath") if symbol_info else None
            
            line_str = ""
            if filepath:
                if i < len(path) - 1:
                    # Find where it calls the next node
                    next_sym = path[i+1]
                    occs = self.repository.get_occurrences_for_symbol(next_sym)
                    call_line = None
                    for occ in occs:
                        if occ["filepath"] == filepath:
                            call_line = occ["start_line"]
                            break
                    if call_line is not None:
                        line_str = f":L{call_line}"
                else:
                    # Last node: find its definition line
                    occs = self.repository.get_occurrences_for_symbol(sym)
                    def_line = None
                    for occ in occs:
                        if occ["filepath"] == filepath and occ["role"] == 1:
                            def_line = occ["start_line"]
                            break
                    if def_line is None and occs:
                        def_line = occs[0]["start_line"]
                    if def_line is not None:
                        line_str = f":L{def_line}"
            
            fp_display = filepath if filepath else "[external]"
            trace_lines.append(f"  {i+1}. {fp_display}{line_str} (symbol: {sym})")
            
        return "\nPath:\n" + "\n".join(trace_lines)

    def _determine_violation_status(self, filepath: str, violation_id: str, file_metadata: dict, violation_overrides: dict) -> tuple[str, Optional[str]]:
        if filepath in file_metadata:
            f_meta = file_metadata[filepath]
            if f_meta.get("manual_status") in ("COMPLIANT", "EXEMPT"):
                justification = f_meta.get("justification") or f"File override: {f_meta.get('manual_status')}"
                return "OVERRIDDEN", justification
        if violation_id in violation_overrides:
            return "OVERRIDDEN", violation_overrides[violation_id]
        return "ACTIVE", None

    def _run_propagation(
        self,
        symbol_classifications: Dict[str, Dict[str, Any]],
        all_edges: List[Dict[str, Any]],
        config: Dict[str, Any]
    ) -> Dict[tuple, str]:
        """
        Runs the dynamic fixed-point worklist propagation algorithm on the call graph.
        Returns a predecessor mapping (child, field_name) -> parent to trace the origin of values.
        """
        propagation_fields = {}
        for prefix, prefix_conf in config.items():
            auto_fields = prefix_conf.get("automatic_fields", {})
            for field_name, field_conf in auto_fields.items():
                if field_conf.get("handler") == "propagation":
                    propagation_fields[field_name] = {
                        "direction": field_conf.get("propagation_direction", "upstream"),
                        "weights": field_conf.get("weights") or {},
                        "barriers": set(field_conf.get("barriers") or []),
                        "barrier_field": field_conf.get("barrier_field") or field_name,
                        "values": field_conf.get("values") or [],
                        "default": field_conf.get("default")
                    }

        if not propagation_fields:
            return {}

        # Build adjacency lists for the call graph
        adj_forward = {}
        adj_backward = {}
        for edge in all_edges:
            src = edge["source"]
            tgt = edge["target"]
            if src in symbol_classifications and tgt in symbol_classifications:
                adj_forward.setdefault(src, set()).add(tgt)
                adj_backward.setdefault(tgt, set()).add(src)

        # Tracks predecessor mappings: (child, field_name) -> parent
        propagation_sources = {}

        for field_name, p_cfg in propagation_fields.items():
            direction = p_cfg["direction"]
            weights = p_cfg["weights"]
            barriers = p_cfg["barriers"]
            barrier_field = p_cfg["barrier_field"]
            values = p_cfg["values"]
            default_val = p_cfg["default"]

            # Map values to integer weights (priority)
            if not weights:
                weights = {val: idx for idx, val in enumerate(values)}

            def get_weight(val):
                if val is None or val == "Unknown":
                    return -1
                return weights.get(val, 0)

            # Determine neighbors traversal function
            if direction == "upstream":
                get_neighbors = lambda n: adj_backward.get(n, [])
            else:
                get_neighbors = lambda n: adj_forward.get(n, [])

            # Initialize worklist with all symbols having non-default values
            worklist = []
            visited = set()
            for sym, data in symbol_classifications.items():
                val = data["fields"].get(field_name, default_val)
                if val is not None and val != default_val:
                    worklist.append(sym)
                    visited.add(sym)

            queue = deque(worklist)
            iterations = 0
            max_iterations = 10000

            while queue and iterations < max_iterations:
                n = queue.popleft()
                visited.discard(n)
                iterations += 1

                n_val = symbol_classifications[n]["fields"].get(field_name, default_val)
                n_weight = get_weight(n_val)

                for m in get_neighbors(n):
                    # Check barriers on neighbor node `m`
                    m_barrier_val = symbol_classifications[m]["fields"].get(barrier_field, default_val)
                    if m_barrier_val in barriers:
                        continue

                    m_val = symbol_classifications[m]["fields"].get(field_name, default_val)
                    m_weight = get_weight(m_val)

                    if n_weight > m_weight:
                        symbol_classifications[m]["fields"][field_name] = n_val
                        propagation_sources[(m, field_name)] = n
                        if m not in visited:
                            queue.append(m)
                            visited.add(m)

        return propagation_sources

    def _matches_blocklist(self, symbol: str, blocklist: List[str]) -> bool:
        """Checks if a symbol matches any pattern in a blocklist."""
        for pattern in blocklist:
            if fnmatch.fnmatch(symbol, pattern):
                return True
        return False

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
                    "DELETE FROM compliance_violations WHERE replace(filepath, '\\', '/') LIKE ?",
                    (f"{normalized_filter}%",)
                )
            else:
                conn.execute("DELETE FROM compliance_violations")

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
            outgoing = self.repository.get_outgoing_edges(sym["symbol"])
            outgoing_calls_map[sym["symbol"]] = [o["target"] for o in outgoing]

        # 3. Classify all symbols dynamically
        file_metadata = self.repository.get_all_files_metadata()
        violation_overrides = self.repository.get_violation_overrides()

        symbol_classifications = {}
        for sym in all_symbols:
            filepath = sym.get("filepath")
            if not filepath:
                continue  # Skip external third-party symbols for classification
                
            prefix_conf = self.get_applicable_config(filepath, config)
            if not prefix_conf:
                continue

            outgoing = outgoing_calls_map.get(sym["symbol"], [])
            classifications = self.assign_automatic_fields(sym, prefix_conf, outgoing)
            
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
        propagation_sources = self._run_propagation(symbol_classifications, all_edges, config)

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
                        
                        if source_val == forbidden_source and self._matches_blocklist(target_sym, blocklist):
                            msg = rule.get("message", f"Package restriction violation: {source_val} cannot depend on {target_sym}")
                            
                            # Retrieve coordinate line number
                            line_number = 1
                            occs = self.repository.get_occurrences_for_symbol(target_sym)
                            for occ in occs:
                                if occ["filepath"] == filepath:
                                    line_number = occ["start_line"]
                                    break
                                    
                            violation_text = f"{source_sym}_{target_sym}_pkg_restrict_{forbidden_source}"
                            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                            rule_id = f"{field_name}_pkg_{forbidden_source}".lower().replace("/", "_").replace(".", "_")
                            
                            status, justification = self._determine_violation_status(
                                filepath, violation_id, file_metadata, violation_overrides
                            )
                            violation_data = {
                                "violation_id": violation_id,
                                "rule_id": rule_id,
                                "symbol": source_sym,
                                "filepath": filepath,
                                "line": line_number,
                                "message": msg,
                                "status": status,
                                "justification": justification
                            }
                            violations.append(violation_data)
                            self.repository.add_violation(**violation_data)

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
                                trace_msg = msg + self._format_path_trace(final_path)
                                
                                # Retrieve coordinate line number
                                line_number = 1
                                occs = self.repository.get_occurrences_for_symbol(target_sym)
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
                                    
                                status, justification = self._determine_violation_status(
                                    filepath, violation_id, file_metadata, violation_overrides
                                )
                                violation_data = {
                                    "violation_id": violation_id,
                                    "rule_id": rule_id,
                                    "symbol": source_sym,
                                    "filepath": filepath,
                                    "line": line_number,
                                    "message": trace_msg,
                                    "status": status,
                                    "justification": justification
                                }
                                violations.append(violation_data)
                                self.repository.add_violation(**violation_data)

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
                        simple_name = self._get_simple_name(sym)
                        violated = False
                        if suffix and not simple_name.endswith(suffix):
                            violated = True
                        if prefix_pattern and not simple_name.startswith(prefix_pattern):
                            violated = True
                            
                        if violated:
                            msg = rule.get("message", f"Naming convention violation: '{simple_name}' must match constraints for {classification}")
                            
                            # Find definition line
                            line_number = 1
                            occs = self.repository.get_occurrences_for_symbol(sym)
                            for occ in occs:
                                if occ["filepath"] == filepath and occ["role"] == 1:
                                    line_number = occ["start_line"]
                                    break
                            if line_number == 1 and occs:
                                line_number = occs[0]["start_line"]
                                
                            violation_text = f"{sym}_naming_{classification}"
                            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                            rule_id = f"naming_{classification}".lower().replace("/", "_").replace(".", "_")
                            
                            status, justification = self._determine_violation_status(
                                filepath, violation_id, file_metadata, violation_overrides
                            )
                            violation_data = {
                                "violation_id": violation_id,
                                "rule_id": rule_id,
                                "symbol": sym,
                                "filepath": filepath,
                                "line": line_number,
                                "message": msg,
                                "status": status,
                                "justification": justification
                            }
                            violations.append(violation_data)
                            self.repository.add_violation(**violation_data)

        # Re-compute automated status for all files based on active violations
        violations_by_file = {}
        for v in violations:
            v_filepath = v["filepath"]
            violations_by_file.setdefault(v_filepath, []).append(v["status"])

        for f_path in file_metadata.keys():
            v_statuses = violations_by_file.get(f_path, [])
            if not v_statuses:
                new_status = "COMPLIANT"
            elif any(s == "ACTIVE" for s in v_statuses):
                new_status = "VIOLATION_DETECTED"
            else:
                new_status = "COMPLIANT"
            self.repository.update_file_status(f_path, new_status)

        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.")
        return violations
