from typing import Dict, List, Any, Optional
from auditor.path_tracer import format_path_trace, matches_blocklist
from auditor.snapshot import AuditSnapshot
from utils.arch_config import ArchConfig, build_rule_id
from utils.helpers import matches_filter, find_call_site_or_definition_line, demangle_scip_symbol
from utils.violation_id import generate_violation_id


def _trace_propagation_path(
    source_sym: str,
    target_sym: str,
    field_name: str,
    propagation_sources: Dict[tuple, str],
    field_conf: Any,
) -> List[str]:
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
        path = src_path if src_path[-1] == target_sym else src_path + tgt_path
    else:
        path = list(reversed(src_path)) + list(reversed(tgt_path))

    seen = set()
    return [node for node in path if node not in seen and not seen.add(node)]


def _find_counterfactual_fix(
    target_sym: str,
    target_data: Dict[str, Any],
    field_name: str,
    field_conf: Any,
    symbol_classifications: Dict[str, Any],
    snapshot: Optional[AuditSnapshot] = None,
) -> Optional[str]:
    barriers = field_conf.get("barriers", [])
    if not barriers:
        return None
    barrier_field = field_conf.barrier_field if hasattr(field_conf, "barrier_field") else (field_conf.get("barrier_field") or field_name)

    incoming = snapshot.get_incoming(target_sym) if snapshot is not None else []
    parent_sym = target_data.get("symbol_info", {}).get("parent_symbol")
    if parent_sym and snapshot is not None:
        incoming = incoming + snapshot.get_incoming(parent_sym)

    candidates = []
    seen_callers = set()
    for edge in incoming:
        caller = edge.get("source")
        if not caller or caller.startswith("local ") or caller in seen_callers or caller not in symbol_classifications:
            continue
        seen_callers.add(caller)
        caller_layer = symbol_classifications[caller]["fields"].get(barrier_field)
        if caller_layer in barriers:
            clean_caller = demangle_scip_symbol(caller)
            clean_target = demangle_scip_symbol(target_sym)
            candidates.append(f"`{clean_caller}` (in {caller_layer}) already calls `{clean_target}`")
            if len(candidates) >= 2:
                break
    if candidates:
        return f"Delegate through existing barrier intermediary in {'/'.join(barriers)}: " + "; ".join(candidates)
    return None


def _check_package_restrictions(
    rule: Any,
    source_sym: str,
    target_sym: str,
    source_data: Dict[str, Any],
    filepath: str,
    matched_prefix: Optional[str],
    field_name: str,
    edge: Optional[Dict[str, Any]] = None,
    snapshot: Optional[AuditSnapshot] = None,
) -> List[Dict[str, Any]]:
    source_val = source_data["static_fields"].get(field_name)
    forbidden_source = rule.get("source")
    blocklist = rule.get("blocklist", [])
    if source_val != forbidden_source or not matches_blocklist(target_sym, blocklist):
        return []
    msg = rule.get("message", f"Package restriction violation: {source_val} cannot depend on {target_sym}")
    line_number = find_call_site_or_definition_line(source_sym, target_sym, edge=edge, snapshot=snapshot)
    violation_id = generate_violation_id(source_sym, target_sym, "pkg_restrict", forbidden_source)
    rule_id = build_rule_id(matched_prefix, field_name, "package_restriction", source=forbidden_source)
    return [{
        "violation_id": violation_id,
        "rule_id": rule_id,
        "symbol": source_sym,
        "filepath": filepath,
        "line": line_number,
        "message": msg,
        "origin": "automatic",
    }]


def _check_single_dependency(
    rule: Any,
    source_sym: str,
    target_sym: str,
    source_data: Dict[str, Any],
    target_data: Dict[str, Any],
    filepath: str,
    matched_prefix: Optional[str],
    field_name: str,
    propagation_sources: Dict[tuple, str],
    field_conf: Any,
    symbol_classifications: Dict[str, Any],
    edge: Optional[Dict[str, Any]] = None,
    snapshot: Optional[AuditSnapshot] = None,
) -> Optional[Dict[str, Any]]:
    source_val = source_data["static_fields"].get(field_name)
    target_val = target_data["fields"].get(field_name)
    if source_val is None or target_val is None:
        return None
    forbidden_source, forbidden_target = rule.get("source"), rule.get("target")
    if source_val != forbidden_source or target_val != forbidden_target:
        return None

    msg = rule.get("message", f"Dependency violation: {source_val} is not allowed to call {target_val}")
    path = _trace_propagation_path(source_sym, target_sym, field_name, propagation_sources, field_conf)
    trace_msg = msg + format_path_trace(path, snapshot=snapshot)

    fix_hint = _find_counterfactual_fix(target_sym, target_data, field_name, field_conf, symbol_classifications, snapshot=snapshot)
    if fix_hint:
        trace_msg += f"\n  Suggested Fix: {fix_hint}"
    line_number = find_call_site_or_definition_line(source_sym, target_sym, edge=edge, snapshot=snapshot)

    violation_id = generate_violation_id(source_sym, target_sym, field_name, forbidden_source, forbidden_target)
    rule_id = build_rule_id(
        matched_prefix,
        field_name,
        "dependency_check",
        source=forbidden_source,
        target=forbidden_target,
    )

    return {
        "violation_id": violation_id,
        "rule_id": rule_id,
        "symbol": source_sym,
        "filepath": filepath,
        "line": line_number,
        "message": trace_msg,
        "origin": "automatic",
    }


def check(
    snapshot: AuditSnapshot,
    symbol_classifications: Dict[str, Any],
    propagation_sources: Dict[str, Any],
    config: Any,
    filepath_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Checks dependency and package restriction rules for architectural boundary compliance."""
    cfg = config if isinstance(config, ArchConfig) else ArchConfig.from_dict(config)
    violations: List[Dict[str, Any]] = []
    edges_to_check = snapshot.all_edges if snapshot else []
    classifications = symbol_classifications or {}
    prop_sources = propagation_sources or {}

    for edge in edges_to_check:
        source_sym, target_sym = edge["source"], edge["target"]
        if source_sym not in classifications:
            continue
        source_data = classifications[source_sym]
        filepath = source_data["symbol_info"]["filepath"]
        if not filepath or not matches_filter(filepath, filepath_filter):
            continue

        matched_prefix = cfg.get_applicable_prefix(filepath)
        prefix_conf = cfg.prefixes.get(matched_prefix) if matched_prefix else None
        if not prefix_conf:
            continue

        for field_name, field_conf in prefix_conf.automatic_fields.items():
            for rule in field_conf.get("rules", []):
                rule_type = rule.get("rule_type", "dependency_boundary")
                if rule_type == "package_restriction":
                    violations.extend(
                        _check_package_restrictions(
                            rule, source_sym, target_sym, source_data,
                            filepath, matched_prefix, field_name,
                            edge=edge, snapshot=snapshot,
                        )
                    )
                elif rule_type in ("dependency_boundary", "dependency_check") and target_sym in classifications:
                    target_data = classifications[target_sym]
                    v = _check_single_dependency(
                        rule, source_sym, target_sym, source_data, target_data,
                        filepath, matched_prefix, field_name, prop_sources,
                        field_conf, classifications, edge=edge, snapshot=snapshot,
                    )
                    if v:
                        violations.append(v)

    return violations
