from typing import Dict, List, Any, Optional
from db.repository import Repository
from auditor.condition_registry import ConditionEvaluatorRegistry


class SymbolClassifier:
    """
    Evaluates classification conditions for code symbols and assigns automatic fields.
    Uses ConditionEvaluatorRegistry for extensible condition evaluation.
    """
    def __init__(self, repository: Repository):
        self.repository = repository

    def evaluate_conditions(
        self,
        symbol_info: Dict[str, Any],
        conditions: Dict[str, Any],
        outgoing_targets: List[str],
        symbol_to_filepath: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Returns True if a symbol definition meets all the specified assignment conditions.
        Delegates each condition type to the registered evaluator in ConditionEvaluatorRegistry.
        """
        for condition_type, value in conditions.items():
            if not ConditionEvaluatorRegistry.evaluate(
                condition_type, symbol_info, value,
                outgoing_targets=outgoing_targets,
                repository=self.repository,
                symbol_to_filepath=symbol_to_filepath
            ):
                return False
        return True

    def assign_automatic_fields(
        self,
        symbol_info: Dict[str, Any],
        prefix_conf: Dict[str, Any],
        outgoing_targets: List[str],
        symbol_to_filepath: Optional[Dict[str, str]] = None
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
                
                if self.evaluate_conditions(symbol_info, conditions, outgoing_targets, symbol_to_filepath=symbol_to_filepath):
                    assigned_val = target_value
                    break
                    
            assigned_values[field_name] = assigned_val
            
        return assigned_values
