from pathlib import Path
from typing import Any, Dict, List
from auditor.analyzer import Auditor
from utils.helpers import demangle_scip_symbol

_SEVERITY_ORDER = ("Critical", "Error", "Warning", "Info", "Manual")


def _format_severity_counts(by_severity: Dict[str, int]) -> str:
    parts: List[str] = []
    seen = set()
    for sev in _SEVERITY_ORDER:
        cnt = by_severity.get(sev, 0)
        if cnt > 0:
            parts.append(f"{sev}: {cnt}")
            seen.add(sev)
    for sev in sorted(by_severity.keys()):
        if sev not in seen and by_severity[sev] > 0:
            parts.append(f"{sev}: {by_severity[sev]}")
    return ", ".join(parts)


def handle_audit(repository, project_root, summary_only: bool = False) -> str:
    """Run the project-wide compliance audit with a compact scorecard rollup. Returns markdown."""
    root_path = Path(project_root) if isinstance(project_root, str) else project_root
    auditor = Auditor(repository, root_path)
    auditor.run_audit()

    summary = repository.analytics.get_compliance_summary(top_files=5)
    total_f = summary["total_files"]
    comp_f = summary["compliant_files"]
    viol_f = summary["violating_files"]
    pend_f = summary["pending_audit"]
    overrides = summary["manual_overrides"]
    pct = round((comp_f / total_f) * 100, 1) if total_f > 0 else 100.0

    posture_parts = [
        f"{comp_f}/{total_f} compliant ({pct}%)",
        f"{viol_f} violating",
        f"{pend_f} pending audit",
    ]
    if overrides > 0:
        posture_parts.append(f"{overrides} manual override(s)")

    total_v = summary["total_violations"]
    auto_v = summary["automatic_violations"]
    man_v = summary["manual_violations"]
    sev_str = _format_severity_counts(summary["by_severity"])

    header_lines: List[str] = []
    if total_f > 0:
        header_lines.append(f"- **Posture**: {' | '.join(posture_parts)}")
    if total_v > 0:
        sev_suffix = f" — {sev_str}" if sev_str else ""
        header_lines.append(f"- **Rule Violations**: {total_v} ({auto_v} automatic, {man_v} manual){sev_suffix}")
        for r in summary["by_rule"]:
            header_lines.append(
                f"  - `{r['rule_id']}` [{r['severity']}]: {r['count']} hit(s) in {r['file_count']} file(s) — {r['description']}"
            )

    if summary_only:
        md = ["## Compliance Audit Summary\n"]
        if header_lines:
            md.extend(header_lines)
        if summary["hotspot_files"]:
            hot_str = ", ".join(f"`{h['filepath']}` ({h['count']})" for h in summary["hotspot_files"])
            md.append(f"- **Hotspot Files**: {hot_str}")
        if total_v == 0:
            md.append("\n**No boundary rule violations found** project-wide.")
        return "\n".join(md)

    all_violations = repository.quality.get_violations()
    if not all_violations:
        md = ["## Compliance Audit\n"]
        if header_lines:
            md.extend(header_lines)
            md.append("")
        pending_msg = (
            f"\n\n*{pend_f} file(s) pending deep audit.*" if pend_f > 0 else ""
        )
        md.append(f"**No boundary rule violations found** project-wide.{pending_msg}")
        return "\n".join(md)

    rule_violations = [v for v in all_violations if v.get("rule_id") != "pending_audit"]
    pending_violations = [v for v in all_violations if v.get("rule_id") == "pending_audit"]

    def _clean_message(v: Dict[str, Any]) -> str:
        msg = (v.get("message") or "").strip()
        fp = v.get("filepath") or ""
        if fp and msg.startswith(f"{fp}: "):
            msg = msg[len(fp) + 2:].strip()
        elif fp and msg.startswith(f"{fp} "):
            msg = msg[len(fp) + 1:].strip()
        return msg

    def _format_rule_violation(v: Dict[str, Any]) -> str:
        fp = v.get("filepath", "")
        line = v.get("line", 1)
        rule = v.get("rule_id", "rule")
        sym = demangle_scip_symbol(v["symbol"]) if v.get("symbol") else None
        msg = _clean_message(v)

        sym_str = f" (`{sym}`)" if sym else ""
        return f"- `{fp}:L{line}` **[{rule}]**{sym_str}: {msg}"

    md = [f"## Compliance Audit: {len(all_violations)} finding(s)\n"]
    if header_lines:
        md.extend(header_lines)
        md.append("")

    if rule_violations and pending_violations:
        md.append(f"### Architectural Rule Violations ({len(rule_violations)})\n")
        for v in sorted(rule_violations, key=lambda x: (x.get("filepath", ""), x.get("line", 0))):
            md.append(_format_rule_violation(v))
        md.append("")

        md.append(f"### Files Pending Deep Audit ({len(pending_violations)})\n")
        md.append("> Files modified or added since last baseline. Run `clear_pending` to acknowledge.\n")
        for v in sorted(pending_violations, key=lambda x: x.get("filepath", "")):
            fp = v.get("filepath", "")
            msg = _clean_message(v)
            desc = f" ({msg})" if msg else ""
            md.append(f"- `{fp}`{desc}")
    elif rule_violations:
        md.append(f"### Architectural Rule Violations ({len(rule_violations)})\n")
        for v in sorted(rule_violations, key=lambda x: (x.get("filepath", ""), x.get("line", 0))):
            md.append(_format_rule_violation(v))
    else:
        md.append("**No boundary rule violations found.**\n")
        md.append(f"### Files Pending Deep Audit ({len(pending_violations)})\n")
        md.append("> Files modified or added since last baseline. Run `clear_pending` to acknowledge.\n")
        for v in sorted(pending_violations, key=lambda x: x.get("filepath", "")):
            fp = v.get("filepath", "")
            msg = _clean_message(v)
            desc = f" ({msg})" if msg else ""
            md.append(f"- `{fp}`{desc}")

    return "\n".join(md)
