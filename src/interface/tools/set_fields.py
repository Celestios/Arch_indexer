import hashlib
import json
from pathlib import Path
from typing import Optional

from auditor.analyzer import Auditor
from interface.validators import resolve_filepath


def handle_set_fields(
    target: str,
    update: Optional[str],
    justification: Optional[str],
    repository,
    project_root: Path,
) -> str:
    """Update manual compliance status or metadata fields for files. Returns markdown."""
    config_path = project_root / ".arch" / "config.json"
    if not config_path.exists():
        return "Error: Ontology config not found at .arch/config.json. Please run 'arch init' first."

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    def validate_file_fields(fp: str, fields: dict) -> Optional[str]:
        normalized_path = fp.replace("\\", "/")
        matching_prefix = None
        for prefix in config.keys():
            if prefix == ".":
                if matching_prefix is None:
                    matching_prefix = "."
            elif normalized_path.startswith(prefix):
                if matching_prefix is None or len(prefix) > len(matching_prefix):
                    matching_prefix = prefix

        if not matching_prefix:
            return f"No configuration prefix matches file '{fp}'."

        prefix_conf = config[matching_prefix]
        manual_cfg = prefix_conf.get("manual_fields", {})
        auto_cfg = prefix_conf.get("automatic_fields", {})

        for f_name, val in fields.items():
            if f_name == "status":
                if str(val).upper() not in ("COMPLIANT", "VIOLATION"):
                    return f"Invalid value '{val}' for field 'status'. Allowed values: 'COMPLIANT', 'VIOLATION'."
                continue
            if f_name in auto_cfg:
                return f"Field '{f_name}' in '{fp}' is an automatic field defined in the ontology and cannot be modified manually."
            if f_name not in manual_cfg:
                return f"Field '{f_name}' is not defined as a manual field in the ontology for prefix '{matching_prefix}'."
            field_conf = manual_cfg[f_name]
            allowed_values = field_conf.get("values")
            if allowed_values is not None:
                if val not in allowed_values:
                    return f"Invalid value '{val}' for manual field '{f_name}' in '{fp}'. Allowed values: {allowed_values}."
            else:
                if not isinstance(val, str):
                    return f"Value for manual field '{f_name}' in '{fp}' must be a string."
        return None

    def apply_updates(fp: str, fields: dict):
        status_val = fields.get("status")
        manual_updates = {k: v for k, v in fields.items() if k != "status"}

        if status_val is not None:
            status_db = "VIOLATION_DETECTED" if status_val.upper() == "VIOLATION" else "COMPLIANT"
            repository.files.update_file_manual_status(fp, status_db, justification)
            repository.compliance.delete_manual_violations(fp)
            if status_db == "VIOLATION_DETECTED":
                violation_text = f"manual_logical_audit_{fp}_{justification or ''}"
                violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]
                repository.compliance.add_violation(
                    violation_id=violation_id,
                    rule_id="logical_audit",
                    symbol=None,
                    filepath=fp,
                    line=1,
                    message=justification or "Manual compliance violation flagged",
                    origin="manual",
                )

        if manual_updates:
            file_info = repository.files.get_file(fp)
            current_fields = {}
            if file_info and file_info.get("manual_fields"):
                try:
                    current_fields = json.loads(file_info["manual_fields"])
                except Exception:
                    pass
            for k, v in manual_updates.items():
                if v is None:
                    current_fields.pop(k, None)
                else:
                    current_fields[k] = v
            repository.files.update_file_manual_fields(fp, current_fields, justification)

    updates_map = {}
    if update is None:
        path_obj = Path(target)
        if not path_obj.is_absolute():
            path_obj = project_root / path_obj
        if not path_obj.exists():
            return f"Error: JSON file not found at {path_obj}"
        with open(path_obj, "r", encoding="utf-8") as f:
            raw_json = json.load(f)
        if not isinstance(raw_json, dict):
            return "Error: JSON file must contain a top-level object mapping filepaths to fields."
        updates_map = raw_json
    else:
        if ":" not in update:
            return "Error: Update parameter must be in the format 'field:value'."
        field, val = update.split(":", 1)
        field = field.strip()
        val = val.strip()
        if val.lower() == "true":
            val = True
        elif val.lower() == "false":
            val = False
        elif val.lower() == "null":
            val = None
        updates_map = {target: {field: val}}

    resolved_updates = {}
    for raw_fp, fields in updates_map.items():
        real_fp = resolve_filepath(repository, raw_fp)
        if not real_fp:
            return f"Error: File '{raw_fp}' is not registered in the database. Please index it first."
        val_err = validate_file_fields(real_fp, fields)
        if val_err:
            return f"Ontology Validation Error: {val_err}"
        resolved_updates[real_fp] = fields

    for real_fp, fields in resolved_updates.items():
        apply_updates(real_fp, fields)

    auditor = Auditor(repository, project_root)
    auditor.run_audit()

    return f"Successfully updated manual fields and compliance status for {len(resolved_updates)} file(s) and re-ran audit."
