from typing import Dict, List, Any, Optional
from auditor.condition_registry import ConditionEvaluatorRegistry


class SymbolClassifier:
    """Pure evaluator for symbol classification conditions and automatic field assignments."""

    def evaluate_conditions(
        self,
        symbol_info: Dict[str, Any],
        conditions: Dict[str, Any],
        outgoing_targets: List[str],
        symbol_to_filepath: Optional[Dict[str, str]] = None,
    ) -> bool:
        for condition_type, value in conditions.items():
            if not ConditionEvaluatorRegistry.evaluate(
                condition_type,
                symbol_info,
                value,
                outgoing_targets=outgoing_targets,
                symbol_to_filepath=symbol_to_filepath,
            ):
                return False
        return True

    def assign_automatic_fields(
        self,
        symbol_info: Dict[str, Any],
        prefix_conf: Any,
        outgoing_targets: List[str],
        symbol_to_filepath: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        assigned_values = {}
        auto_fields = prefix_conf.get("automatic_fields", {})

        for field_name, field_conf in auto_fields.items():
            assigned_val = field_conf.get("default")
            for rule in field_conf.get("assignment_rules", []):
                if self.evaluate_conditions(
                    symbol_info,
                    rule.get("conditions", {}),
                    outgoing_targets,
                    symbol_to_filepath=symbol_to_filepath,
                ):
                    assigned_val = rule.get("value")
                    break
            assigned_values[field_name] = assigned_val

        return assigned_values
