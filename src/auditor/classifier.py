from typing import Dict, List, Any
from db.repository import Repository

class SymbolClassifier:
    """
    Evaluates classification conditions for code symbols and assigns automatic fields.
    """
    def __init__(self, repository: Repository):
        self.repository = repository

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
                target_node = self.repository.symbols.get_symbol(target)
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
