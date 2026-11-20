from typing import Dict, List, Any, Optional
from db.repository import Repository
from auditor.violation_checkers.base import BaseViolationChecker
from utils.helpers import matches_filter
from utils.violation_id import ViolationId


class PendingAuditChecker(BaseViolationChecker):
    """Checks pending audit files for architectural boundary compliance."""

    def __init__(self, repository: Optional[Repository] = None):
        super().__init__(repository)

    def check(
        self,
        snapshot: Any,
        symbol_classifications: Any = None,
        config: Any = None,
        filepath_filter: Optional[str] = None,
        propagation_sources: Optional[Dict] = None,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        from auditor.snapshot import AuditSnapshot

        if isinstance(snapshot, AuditSnapshot):
            snap = snapshot
            fp_filter = filepath_filter
        else:
            fp_filter = filepath_filter
            snap = kwargs.get("snapshot")

        violations = []
        if snap is not None and snap.all_files:
            file_metadata = snap.all_files
        elif self.repository is not None:
            file_metadata = self.repository.files.get_all_files_metadata()
        else:
            file_metadata = {}

        for f_path, meta in file_metadata.items():
            if not meta.get("pending_audit"):
                continue
            if not matches_filter(f_path, fp_filter):
                continue
            justification_msg = meta.get("justification") or ""
            msg = f"{f_path}: file changed" if "modified" in justification_msg.lower() or "changed" in justification_msg.lower() else f"{f_path}: new file"
            violation_id = ViolationId.generate("pending_audit", f_path)
            vdata = {"violation_id": violation_id, "rule_id": "pending_audit", "symbol": None,
                     "filepath": f_path, "line": 1, "message": msg, "origin": "automatic"}
            violations.append(vdata)
        return violations
