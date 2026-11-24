from pathlib import Path
from typing import Any, Dict, List

from auditor.analyzer import Auditor
from utils.symbol_id import canonical_display_name

_SEVERITY_ORDER = ("Critical", "Error", "Warning", "Info")


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
    """Run the project-wide compliance audit with a 3-axis scorecard rollup. Returns markdown."""
    root_path = Path(project_root) if isinstance(project_root, str) else project_root
    auditor = Auditor(repository, root_path)
    auditor.run_audit()

    summary = repository.analytics.get_compliance_summary(top_files=5)
    total_f = summary["total_files"]
    comp_f = summary["compliant_files"]
    viol_f = summary["violating_files"]
    man_viol_f = summary["manual_violating_files"]
    pend_f = summary["pending_audit"]
    clean_f = summary["clean_files"]
    overrides = summary["manual_overrides"]
    rule_pct = round((comp_f / total_f) * 100, 1) if total_f > 0 else 100.0
    clean_pct = round((clean_f / total_f) * 100, 1) if total_f > 0 else 100.0

    posture_parts = [
        f"{comp_f}/{total_f} rule-compliant ({rule_pct}%)",
        f"{viol_f} rule-violating",
    ]
    if man_viol_f > 0:
        posture_parts.append(f"{man_viol_f} manually flagged")
    if pend_f > 0:
        posture_parts.append(f"{pend_f} pending review")
    if overrides > 0:
        posture_parts.append(f"{overrides} manual override(s)")
    posture_parts.append(f"{clean_f}/{total_f} clean ({clean_pct}%)")

    total_v = summary["total_violations"]
    auto_v = summary["automatic_violations"]
    man_v = summary["manual_violations"]
    sev_str = _format_severity_counts(summary["by_severity"])

    header_lines: List[str] = []
    if total_f > 0:
        header_lines.append(f"- **Posture**: {' | '.join(posture_parts)}")
    if total_v > 0:
        sev_suffix = f" — {sev_str}" if sev_str else ""
        header_lines.append(f"- **Findings**: {total_v} ({auto_v} automatic, {man_v} manual){sev_suffix}")
        for r in summary["by_rule"]:
            origin_tag = "manual" if r.get("origin") == "manual" else "auto"
            header_lines.append(
                f"  - `{r['rule_id']}` [{r['severity']} | {origin_tag}]: {r['count']} hit(s) in {r['file_count']} file(s) — {r['description']}"
            )

    if summary_only:
        md = ["## Compliance Audit Summary\n"]
        if header_lines:
            md.extend(header_lines)
        if summary["hotspot_files"]:
            hot_str = ", ".join(f"`{h['filepath']}` ({h['count']})" for h in summary["hotspot_files"])
            md.append(f"- **Hotspot Files**: {hot_str}")
        if total_v == 0:
            md.append("\n**No rule or manual findings** project-wide.")
        return "\n".join(md)

    all_violations = repository.quality.get_violations()
    pending_files = repository.workspace.get_pending_files()

    auto_violations = [v for v in all_violations if v.get("origin") != "manual"]
    manual_violations = [v for v in all_violations if v.get("origin") == "manual"]

    def _clean_message(v: Dict[str, Any]) -> str:
        msg = (v.get("message") or "").strip()
        fp = v.get("filepath") or ""
        if fp and msg.startswith(f"{fp}: "):
            msg = msg[len(fp) + 2:].strip()
        elif fp and msg.startswith(f"{fp} "):
            msg = msg[len(fp) + 1:].strip()
        return msg

    def _format_violation(v: Dict[str, Any]) -> str:
        fp = v.get("filepath", "")
        line = v.get("line", 1)
        rule = v.get("rule_id", "rule")
        sev = v.get("severity", "Warning")
        sym = canonical_display_name(v["symbol"]) if v.get("symbol") else None
        msg = _clean_message(v)
        sym_str = f" (`{sym}`)" if sym else ""
        return f"- `{fp}:L{line}` **[{rule} | {sev}]**{sym_str}: {msg}"

    title = (
        f"## Compliance Audit: {len(all_violations)} finding(s)"
        if all_violations
        else "## Compliance Audit"
    )
    md = [f"{title}\n"]
    if header_lines:
        md.extend(header_lines)
        md.append("")

    if auto_violations:
        md.append(f"### Automatic Rule Violations ({len(auto_violations)})\n")
        for v in auto_violations:
            md.append(_format_violation(v))
        md.append("")
    else:
        md.append("**No automatic rule violations found** project-wide.\n")

    if manual_violations:
        md.append(f"### Manual Logical Findings ({len(manual_violations)})\n")
        for v in manual_violations:
            md.append(_format_violation(v))
        md.append("")

    if pending_files:
        md.append(f"### Pending Review ({len(pending_files)} files)\n")
        md.append("> Files added or modified since last review (not counted as rule violations). Run `set_status` or `clear_pending` to acknowledge.\n")
        for pf in pending_files:
            fp = pf["filepath"]
            just = (pf.get("justification") or "").strip()
            reason = (
                "modified"
                if "modified" in just.lower() or "changed" in just.lower()
                else (just or "new file")
            )
            md.append(f"- `{fp}` ({reason})")
        md.append("")

    return "\n".join(md).rstrip()
