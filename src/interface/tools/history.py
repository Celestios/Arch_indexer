"""Shared handler for composable on-the-fly Git evolution and risk intelligence."""
import contextlib
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Union

from engines.git_analyzer import run_history_analysis
from interface.validators import validate_sections


def _render_hotspots(data: Dict[str, Any]) -> List[str]:
    items = data.get("items") or []
    mode = data.get("mode", "file")
    target = data.get("target")
    lines: List[str] = []

    if mode == "symbol" and target:
        lines.append(f"### Hotspots (Symbols in `{target}`)")
        fs = data.get("file_summary")
        if fs:
            lines.append(
                f"> File Risk: **{fs['risk_tier']}** (risk={fs['risk_score']} | "
                f"{fs['touches']} touches, {fs['bursts']} bursts, {fs['rework_pct']}% rework, "
                f"fan-in={fs['fan_in']}, cx={fs['max_complexity']}, loc={fs['loc']})"
            )
        for item in items:
            loc_str = (
                f"L{item['start_line']}-{item['end_line']}"
                if item["end_line"] > item["start_line"]
                else f"L{item['start_line']}"
            )
            rev = f", {item['reverts']} rev" if item["reverts"] else ""
            lines.append(
                f"- `{item['symbol']}` ({loc_str}) "
                f"[risk={item['risk_score']} | touches={item['touches']}, bursts={item['bursts']}{rev}, conn={item['connection_weight']}]"
            )
        return lines

    lines.append("### Hotspots (Evolution Risk)")
    if not items:
        lines.append("*No auditable file churn recorded in window.*")
        return lines

    for item in items:
        burst_str = f", bursts={item['bursts']}" if item["bursts"] else ""
        lines.append(
            f"- `{item['filepath']}` [{item['risk_tier']}, risk={item['risk_score']} | "
            f"touches={item['touches']}, fan-in={item['fan_in']}, cx={item['max_complexity']}, "
            f"loc={item['loc']}, rework={item['rework_pct']}%{burst_str}]"
        )
    return lines


def _render_thrash(data: Dict[str, Any]) -> List[str]:
    items = data.get("items") or []
    lines = ["### Thrash (Rework & Burst Loops)"]
    if not items:
        lines.append("*No significant rework loops or touch bursts detected.*")
        return lines

    for item in items:
        rev_str = f", {item['reverts']} revert(s)" if item["reverts"] else ""
        lines.append(
            f"- `{item['filepath']}` [thrash={item['thrash_score']} | "
            f"{item['touches']} touches, {item['bursts']} bursts, {item['rework_pct']}% rework"
            f"{rev_str}, +{item['added']}/-{item['deleted']}]"
        )
    return lines


def _render_coupling(data: Dict[str, Any]) -> List[str]:
    items = data.get("items") or []
    target = data.get("target")
    header = f"### Coupling (Temporal Co-Change for `{target}`)" if target else "### Coupling (Temporal Co-Change)"
    lines = [header]
    if not items:
        lines.append("*No statistically significant co-change pairs found.*")
        return lines

    for item in items:
        tag = item["coupling_type"]
        if target and item.get("filepath"):
            lines.append(
                f"- [{tag}] `{item['filepath']}` "
                f"({item['co_commits']} co-commits, conf={item['confidence_pct']}%, lift={item['lift']}x)"
            )
        else:
            lines.append(
                f"- [{tag}] `{item['file_a']}` <-> `{item['file_b']}` "
                f"({item['co_commits']} co-commits, conf={item['confidence_pct']}%, lift={item['lift']}x)"
            )
    return lines


def _render_growth(data: Dict[str, Any]) -> List[str]:
    items = data.get("items") or []
    lines = ["### Growth (Net Expansion)"]
    if not items:
        lines.append("*No net-growing auditable files in window.*")
        return lines

    for item in items:
        lines.append(
            f"- `{item['filepath']}` [+{item['net_growth']} LOC net | "
            f"now {item['loc']} LOC, cx={item['max_complexity']}, {item['touches']} touches]"
        )
    return lines


def _render_test_gap(data: Dict[str, Any]) -> List[str]:
    items = data.get("items") or []
    lines = ["### Test Gaps (High-Churn Untested)"]
    if not items:
        lines.append("*All high-churn files have static test callers and test co-modifications.*")
        return lines

    for item in items:
        gaps = []
        if item["static_test_callers"] == 0:
            gaps.append("0 static test callers")
        if item["co_modified_tests"] == 0:
            gaps.append(f"0/{item['touches']} commits touched tests")
        lines.append(
            f"- `{item['filepath']}` [{', '.join(gaps)} | "
            f"churn={item['decayed_churn']}, fan-in={item['fan_in']}, touches={item['touches']}]"
        )
    return lines


def _render_archaeology(data: Dict[str, Any]) -> List[str]:
    if data.get("error"):
        return ["### Archaeology", f"*{data['error']}*"]

    label = data.get("target_label") or data.get("filepath") or "target"
    fp = data.get("filepath")
    lr = data.get("line_range")
    loc_suffix = f" (`{fp}:{lr}`)" if (data.get("target_kind") == "symbol" and fp and lr) else ""
    lines = [f"### Archaeology: `{label}`{loc_suffix}"]

    items = data.get("items") or []
    if not items:
        lines.append("*No commit history found for target.*")
        return lines

    for item in items:
        tag_str = " " + " ".join(f"[{t}]" for t in item["tags"]) if item.get("tags") else ""
        delta = f"+{item['added']}/-{item['deleted']}"
        lines.append(f"- `{item['hash']}` ({item['date']}) [{delta}]{tag_str} {item['subject']}")
    return lines


_RENDERERS = {
    "hotspots": _render_hotspots,
    "thrash": _render_thrash,
    "coupling": _render_coupling,
    "growth": _render_growth,
    "test_gap": _render_test_gap,
    "archaeology": _render_archaeology,
}


def handle_history(
    repository,
    project_root: Union[str, Path],
    sections: Optional[Union[List[str], str]] = None,
    target: Optional[str] = None,
    scope: Optional[Union[str, List[str]]] = None,
    commits: int = 100,
    limit: int = 10,
) -> str:
    """
    Runs composable on-the-fly Git evolution analysis across requested sections
    ('hotspots', 'thrash', 'coupling', 'archaeology', 'growth', 'test_gap').
    """
    ok, parsed = validate_sections(sections, has_target=bool(target))
    if not ok:
        return f"Error: {parsed}"
    section_list: List[str] = parsed  # type: ignore[assignment]

    root = Path(project_root).resolve()
    with contextlib.redirect_stdout(sys.stderr):
        res = run_history_analysis(
            repository=repository,
            project_root=root,
            sections=section_list,
            target=target,
            scope=scope,
            commits=max(1, int(commits)),
            limit=max(1, int(limit)),
        )

    if not res.get("is_git_repo"):
        return f"## Git History Analysis\n\n*No Git repository detected at `{root}`.*"

    meta_parts = [f"{res['commits_analyzed']} commits"] if res["commits_analyzed"] else []
    if scope:
        scope_str = ", ".join(scope) if isinstance(scope, list) else str(scope)
        meta_parts.append(f"scope: `{scope_str}`")
    if target:
        meta_parts.append(f"target: `{target}`")

    meta_hdr = f" ({', '.join(meta_parts)})" if meta_parts else ""
    md = [f"## Git History Analysis{meta_hdr}\n"]

    sec_map = res.get("sections", {})
    for sec_name in section_list:
        if sec_name in sec_map and sec_name in _RENDERERS:
            md.extend(_RENDERERS[sec_name](sec_map[sec_name]))
            md.append("")

    return "\n".join(md).rstrip()
