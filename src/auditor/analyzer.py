import os
import json
import sys
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
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
        # To avoid holding connections, we query and load them
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
            
            symbol_classifications[sym["symbol"]] = {
                "symbol_info": sym,
                "fields": classifications,
                "prefix_conf": prefix_conf
            }

        # 4. Audit call graph edges for compliance violations
        violations = []
        
        # We fetch all edges in the database
        all_edges = []
        with self.repository.db_conn.session() as conn:
            res = conn.execute("SELECT source, target, relation FROM edges").fetchall()
            all_edges = [{"source": r[0], "target": r[1], "relation": r[2]} for r in res]

        for edge in all_edges:
            source_sym = edge["source"]
            target_sym = edge["target"]
            
            # We only audit edges where both caller and callee are classified
            if source_sym not in symbol_classifications or target_sym not in symbol_classifications:
                continue
                
            source_data = symbol_classifications[source_sym]
            target_data = symbol_classifications[target_sym]
            
            # Filter by filepath prefix if requested
            if filepath_filter:
                source_fp = source_data["symbol_info"]["filepath"]
                if not source_fp:
                    continue
                norm_source_fp = source_fp.replace("\\", "/")
                norm_filter = filepath_filter.replace("\\", "/")
                if not norm_source_fp.startswith(norm_filter):
                    continue

            # Check dependency rules for each automatic field
            prefix_conf = source_data["prefix_conf"]
            auto_fields = prefix_conf.get("automatic_fields", {})
            
            for field_name, field_conf in auto_fields.items():
                if field_conf.get("handler") == "dependency_check":
                    rules = field_conf.get("rules", [])
                    source_val = source_data["fields"].get(field_name)
                    target_val = target_data["fields"].get(field_name)
                    
                    if source_val is None or target_val is None:
                        continue
                        
                    # Evaluate if there is a constraint mapping source_val -> target_val
                    for rule in rules:
                        forbidden_source = rule.get("source")
                        forbidden_target = rule.get("target")
                        
                        if source_val == forbidden_source and target_val == forbidden_target:
                            msg = rule.get("message", f"Dependency violation: {source_val} is not allowed to call {target_val}")
                            
                            # Retrieve coordinates for occurrence (line number where the call happens)
                            line_number = 1
                            occurrences = self.repository.get_occurrences_for_symbol(target_sym)
                            
                            # Filter occurrences to find caller's source file range
                            filepath = source_data["symbol_info"]["filepath"]
                            for occ in occurrences:
                                if occ["filepath"] == filepath:
                                    line_number = occ["start_line"]
                                    break
                                    
                            # Create a unique violation id
                            violation_text = f"{source_sym}_{target_sym}_{field_name}_{forbidden_source}_{forbidden_target}"
                            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                            
                            rule_id = f"{field_name}_{forbidden_source}_{forbidden_target}".lower().replace("/", "_").replace(".", "_")
                            # If prefix exists, prefix it
                            # We can resolve prefix of source_data
                            # Let's search if config has matching prefix
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
                                "message": msg
                            }
                            violations.append(violation_data)
                            
                            # Persist the violation to DuckDB
                            self.repository.add_violation(
                                violation_id=violation_id,
                                rule_id=rule_id,
                                symbol=source_sym,
                                filepath=filepath,
                                line=line_number,
                                message=msg
                            )
 
        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.")
        return violations

