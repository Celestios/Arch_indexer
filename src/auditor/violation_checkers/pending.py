from typing import Dict, List, Any, Optional

from utils.helpers import matches_filter
from utils.violation_id import ViolationId


class PendingAuditChecker:
    """Checks pending audit files for architectural boundary compliance."""

    def check(self, repository, symbol_classifications: Dict, all_edges: List[Dict],
              config: Dict, filepath_filter: Optional[str],
              propagation_sources: Dict,
              snapshot: Optional[Any] = None) -> List[Dict[str, Any]]:
        violations = []
        if snapshot is not None and snapshot.all_files:
            file_metadata = snapshot.all_files
        else:
            file_metadata = repository.files.get_all_files_metadata()
        for f_path, meta in file_metadata.items():
            if not meta.get("pending_audit"):
                continue
            if not matches_filter(f_path, filepath_filter):
                continue
            justification_msg = meta.get("justification") or ""
            msg = f"{f_path}: file changed" if "modified" in justification_msg.lower() or "changed" in justification_msg.lower() else f"{f_path}: new file"
            violation_id = ViolationId.generate("pending_audit", f_path)
            vdata = {"violation_id": violation_id, "rule_id": "pending_audit", "symbol": None,
                     "filepath": f_path, "line": 1, "message": msg, "origin": "automatic"}
            violations.append(vdata)
        return violations
