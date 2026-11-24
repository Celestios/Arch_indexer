"""Shared handler for updating manual metadata fields on a tracked file."""
import json
from pathlib import Path
from typing import Optional, Tuple

from auditor.analyzer import Auditor


def handle_set_fields(
    repository,
    project_root: Path,
    filepath: str,
    fields_json: str,
    justification: Optional[str] = None,
) -> Tuple[str, bool]:
    """Parses fields_json, updates manual fields, re-audits, and returns (message, ok)."""
    try:
        fields = json.loads(fields_json)
    except Exception as e:
        return f"Error: Invalid JSON fields payload: {e}", False

    if not isinstance(fields, dict):
        return "Error: Fields payload must be a JSON object.", False

    resolved = repository.workspace.resolve_filepath(filepath)
    if not resolved:
        return f"Error: File '{filepath}' is not registered in the database.", False

    file_info = repository.workspace.get_file(resolved)
    current_fields = dict(file_info.get("manual_fields") or {}) if file_info else {}

    for k, v in fields.items():
        if v is None:
            current_fields.pop(k, None)
        else:
            current_fields[k] = v

    repository.workspace.update_manual_fields(resolved, current_fields, justification)
    Auditor(repository, project_root).run_audit()
    return f"Successfully updated manual fields for '{resolved}' to: {current_fields}.", True
