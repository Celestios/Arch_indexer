from typing import Dict, List, Any, Optional
from auditor.snapshot import AuditSnapshot
from utils.helpers import matches_filter
from utils.violation_id import generate_violation_id


def check(
    snapshot: AuditSnapshot,
    symbol_classifications: Dict[str, Any],
    propagation_sources: Dict[str, Any],
    config: Any,
    filepath_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Checks pending audit files for architectural boundary compliance."""
    violations: List[Dict[str, Any]] = []
    file_metadata = snapshot.all_files if snapshot else {}

    for f_path, meta in file_metadata.items():
        if not meta.get("pending_audit"):
            continue
        if not matches_filter(f_path, filepath_filter):
            continue
        justification_msg = meta.get("justification") or ""
        msg = (
            "file changed"
            if "modified" in justification_msg.lower() or "changed" in justification_msg.lower()
            else "new file"
        )
        violation_id = generate_violation_id("pending_audit", f_path)
        violations.append({
            "violation_id": violation_id,
            "rule_id": "pending_audit",
            "symbol": None,
            "filepath": f_path,
            "line": 1,
            "message": msg,
            "origin": "automatic",
        })
    return violations
