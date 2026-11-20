from auditor.analyzer import Auditor
from utils.helpers import demangle_scip_symbol


def handle_audit(repository, project_root) -> str:
    """Run the project-wide compliance audit. Returns markdown."""
    auditor = Auditor(repository, project_root)
    violations = auditor.run_audit()
    all_violations = repository.compliance.get_violations()

    if not all_violations:
        pending_count = repository.files.get_files_pending_audit_count()
        pending_msg = (
            f"\n\n*{pending_count} file(s) pending deep audit.*" if pending_count > 0 else ""
        )
        return f"## Compliance Audit\n\n**No boundary rule violations found** project-wide.{pending_msg}"

    md = [f"## Compliance Audit: {len(all_violations)} finding(s)\n"]
    for i, v in enumerate(all_violations, 1):
        md.append(f"{i}. **[{v['rule_id']}]** (`{v['filepath']}:L{v['line']}`)")
        if v["symbol"]:
            clean_sym = demangle_scip_symbol(v["symbol"])
            md.append(f"   - Symbol: `{clean_sym}`")
        md.append(f"   - {v['message']}")
        md.append("")
    return "\n".join(md)

