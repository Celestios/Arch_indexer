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
        symbol_classifications: Any,
        all_edges: Any = None,
        config: Any = None,
        filepath_filter: Optional[str] = None,
        propagation_sources: Optional[Dict] = None,
        snapshot: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        repo = self.repository
        if not isinstance(symbol_classifications, dict) and hasattr(symbol_classifications, "files"):
            repo = symbol_classifications
            symbol_classifications, all_edges, config, filepath_filter, propagation_sources = (
                all_edges, config, filepath_filter, propagation_sources, snapshot
            )
            snapshot = None

        violations = []
        if snapshot is not None and snapshot.all_files:
            file_metadata = snapshot.all_files
        elif repo is not None:
            file_metadata = repo.files.get_all_files_metadata()
        else:
            file_metadata = {}

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
