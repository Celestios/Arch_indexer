from typing import Any, Callable, Dict, List, Optional

from utils.symbol_id import parse_canonical_id, strip_rust_generics


class ConditionEvaluatorRegistry:
    """Registry for condition evaluators."""

    _evaluators: Dict[str, Callable] = {}

    @classmethod
    def register(cls, condition_type: str, evaluator: Callable) -> None:
        cls._evaluators[condition_type] = evaluator

    @classmethod
    def evaluate(
        cls,
        condition_type: str,
        symbol_info: Dict,
        value: Any,
        outgoing_targets: Optional[List] = None,
        **kwargs,
    ) -> bool:
        evaluator = cls._evaluators.get(condition_type)
        if not evaluator:
            raise ValueError(f"Unknown condition type: {condition_type}")
        if outgoing_targets is not None:
            return evaluator(symbol_info, value, outgoing_targets=outgoing_targets, **kwargs)
        return evaluator(symbol_info, value, **kwargs)

    @classmethod
    def list_types(cls) -> list:
        return list(cls._evaluators.keys())

    @classmethod
    def clear(cls) -> None:
        cls._evaluators.clear()


def _eval_path_prefix(symbol_info: dict, prefix: str, **kwargs) -> bool:
    filepath = symbol_info.get("filepath")
    return bool(filepath and filepath.replace("\\", "/").startswith(prefix))


def _eval_class_suffix(symbol_info: dict, suffix: str, **kwargs) -> bool:
    _, scope_parts, leaf = parse_canonical_id(symbol_info["symbol"])
    name = symbol_info.get("name") or leaf
    if name.endswith(suffix):
        return True
    if scope_parts and strip_rust_generics(scope_parts[-1]).endswith(suffix):
        return True
    return False


def _eval_class_contains(symbol_info: dict, substring: str, **kwargs) -> bool:
    _, scope_parts, leaf = parse_canonical_id(symbol_info["symbol"])
    name = symbol_info.get("name") or leaf
    if substring in name:
        return True
    return any(substring in strip_rust_generics(s) for s in scope_parts)


def _eval_name_contains(symbol_info: dict, substring: str, **kwargs) -> bool:
    _, _, leaf = parse_canonical_id(symbol_info["symbol"])
    name = symbol_info.get("name") or leaf
    return substring in name


def _eval_calls_prefix(
    symbol_info: dict,
    prefix: str,
    outgoing_targets: Optional[List] = None,
    **kwargs,
) -> bool:
    """Evaluates calls_prefix condition purely in-memory via symbol_to_filepath."""
    if not outgoing_targets:
        return False
    symbol_to_filepath = kwargs.get("symbol_to_filepath") or {}
    for target in outgoing_targets:
        target_path = symbol_to_filepath.get(target)
        if target_path and target_path.replace("\\", "/").startswith(prefix):
            return True
    return False


ConditionEvaluatorRegistry.register("path_prefix", _eval_path_prefix)
ConditionEvaluatorRegistry.register("class_suffix", _eval_class_suffix)
ConditionEvaluatorRegistry.register("class_contains", _eval_class_contains)
ConditionEvaluatorRegistry.register("name_contains", _eval_name_contains)
ConditionEvaluatorRegistry.register("calls_prefix", _eval_calls_prefix)
