from typing import Dict, Callable, Any


class ConditionEvaluatorRegistry:
    """
    Registry for condition evaluators. New condition types added by registration.
    Replaces hardcoded condition dispatch in SymbolClassifier.evaluate_conditions().
    """
    
    _evaluators: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, condition_type: str, evaluator: Callable) -> None:
        """Register a condition evaluator function."""
        cls._evaluators[condition_type] = evaluator
    
    @classmethod
    def evaluate(cls, condition_type: str, symbol_info: Dict, 
                 value: Any, outgoing_targets: list = None, **kwargs) -> bool:
        """Evaluate a condition using the registered evaluator."""
        evaluator = cls._evaluators.get(condition_type)
        if not evaluator:
            raise ValueError(f"Unknown condition type: {condition_type}")
        if outgoing_targets is not None:
            return evaluator(symbol_info, value, outgoing_targets=outgoing_targets, **kwargs)
        return evaluator(symbol_info, value, **kwargs)
    
    @classmethod
    def list_types(cls) -> list:
        """List all registered condition types."""
        return list(cls._evaluators.keys())
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered evaluators (for testing)."""
        cls._evaluators.clear()


# Built-in condition evaluators
def _eval_path_prefix(symbol_info: dict, prefix: str, **kwargs) -> bool:
    filepath = symbol_info.get("filepath")
    return bool(filepath and filepath.replace("\\", "/").startswith(prefix))

def _eval_class_suffix(symbol_info: dict, suffix: str, **kwargs) -> bool:
    name = symbol_info["symbol"].split(" ")[-1]
    return name.endswith(suffix)

def _eval_class_contains(symbol_info: dict, substring: str, **kwargs) -> bool:
    name = symbol_info["symbol"].split(" ")[-1]
    return substring in name

def _eval_name_contains(symbol_info: dict, substring: str, **kwargs) -> bool:
    name = symbol_info["symbol"].split(" ")[-1]
    return substring in name

def _eval_calls_prefix(symbol_info: dict, prefix: str, outgoing_targets: list = None, **kwargs) -> bool:
    """Evaluates calls_prefix condition. Requires repository from kwargs."""
    if not outgoing_targets:
        return False
    repository = kwargs.get("repository")
    if not repository:
        return False
    for target in outgoing_targets:
        target_node = repository.symbols.get_symbol(target)
        if target_node and target_node.get("filepath"):
            if target_node["filepath"].replace("\\", "/").startswith(prefix):
                return True
    return False


# Register built-in evaluators
ConditionEvaluatorRegistry.register("path_prefix", _eval_path_prefix)
ConditionEvaluatorRegistry.register("class_suffix", _eval_class_suffix)
ConditionEvaluatorRegistry.register("class_contains", _eval_class_contains)
ConditionEvaluatorRegistry.register("name_contains", _eval_name_contains)
ConditionEvaluatorRegistry.register("calls_prefix", _eval_calls_prefix)
