from typing import Dict, List, Any, Optional
from utils.helpers import matches_filter
from utils.violation_id import ViolationId
from auditor.snapshot import AuditSnapshot


def check(
    snapshot: AuditSnapshot,
    symbol_classifications: Dict[str, Any],
    propagation_sources: Dict[str, Any],
    config: Any,
    filepath_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Checks pending audit files for architectural boundary compliance."""
    violations = []
    file_metadata = snapshot.all_files if snapshot and hasattr(snapshot, "all_files") else {}

    for f_path, meta in file_metadata.items():
        if not meta.get("pending_audit"):
            continue
        if not matches_filter(f_path, filepath_filter):
            continue
        justification_msg = meta.get("justification") or ""
        msg = (
            f"{f_path}: file changed"
            if "modified" in justification_msg.lower() or "changed" in justification_msg.lower()
            else f"{f_path}: new file"
        )
        violation_id = ViolationId.generate("pending_audit", f_path)
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
