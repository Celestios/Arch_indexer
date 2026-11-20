import sys
from typing import Dict, Any

from db.repository import Repository
from auditor.config_loader import ConfigLoader


class FieldValidator:
    """Validates and resets manual fields based on config rules."""

    def __init__(self, repository: Repository, config_loader: ConfigLoader):
        self.repository = repository
        self.config_loader = config_loader

    def reset_invalid_manual_fields(self, config: Dict[str, Any]):
        """Resets manual fields that are no longer valid or need resetting on file change."""
        file_metadata = self.repository.workspace.get_all_files_metadata()
        db_updated = False

        for filepath, meta in file_metadata.items():
            prefix_conf = self.config_loader.get_applicable_config(filepath, config)
            if not prefix_conf:
                continue

            manual_cfg = prefix_conf.get("manual_fields", {})
            current_manual_fields = meta.get("manual_fields") or {}
            updated_fields = dict(current_manual_fields)
            fields_to_reset = []
            justification = meta.get("justification") or ""
            is_modified = meta.get("is_modified")
            if is_modified is None:
                is_modified = bool(
                    meta.get("pending_audit")
                    and ("modified" in justification.lower() or justification.startswith("File modified"))
                )
            fields_changed = False

            for field_name, field_conf in manual_cfg.items():
                default_val = field_conf.get("default")
                allowed_values = field_conf.get("values")
                reset_on_change = field_conf.get("reset_on_change", False)
                curr_val = current_manual_fields.get(field_name)

                if curr_val is not None and allowed_values is not None and curr_val not in allowed_values:
                    print(
                        f"warning: value '{curr_val}' for manual field '{field_name}' in '{filepath}' is no longer allowed. "
                        f"Resetting to default '{default_val}' and marking for audit.",
                        file=sys.stderr
                    )
                    updated_fields[field_name] = default_val
                    fields_changed = True
                    justification_msg = f"Manual field '{field_name}' value '{curr_val}' not allowed by config, reset to default."
                    self.repository.workspace.mark_file_for_audit(filepath, justification_msg)
                    db_updated = True
                elif is_modified and reset_on_change:
                    if curr_val != default_val:
                        updated_fields[field_name] = default_val
                        fields_changed = True
                        fields_to_reset.append(field_name)

            if fields_changed:
                if is_modified and fields_to_reset:
                    reset_msg = ", ".join(fields_to_reset)
                    new_justification = f"File modified, pending re-audit (fields reset: {reset_msg})"
                    self.repository.workspace.set_manual_fields(filepath, updated_fields, new_justification)
                else:
                    self.repository.workspace.set_manual_fields(filepath, updated_fields, justification)
                db_updated = True
