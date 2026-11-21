import sys
from typing import Any

from db.repository import Repository
from utils.arch_config import ArchConfig


class FieldValidator:
    """Validates and resets manual fields based on ArchConfig rules."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def reset_invalid_manual_fields(self, config: Any):
        cfg = config if isinstance(config, ArchConfig) else ArchConfig.from_dict(config)
        file_metadata = self.repository.workspace.get_all_files_metadata()

        for filepath, meta in file_metadata.items():
            prefix_conf = cfg.get_applicable_config(filepath)
            if not prefix_conf:
                continue

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

            for field_name, field_conf in prefix_conf.manual_fields.items():
                default_val = field_conf.get("default")
                allowed_values = field_conf.get("values")
                reset_on_change = field_conf.get("reset_on_change", False)
                curr_val = current_manual_fields.get(field_name)

                if curr_val is not None and allowed_values is not None and curr_val not in allowed_values:
                    print(
                        f"warning: value '{curr_val}' for manual field '{field_name}' in '{filepath}' is no longer allowed. "
                        f"Resetting to default '{default_val}' and marking for audit.",
                        file=sys.stderr,
                    )
                    updated_fields[field_name] = default_val
                    fields_changed = True
                    justification_msg = f"Manual field '{field_name}' value '{curr_val}' not allowed by config, reset to default."
                    self.repository.workspace.update_mark_file_pending(filepath, justification_msg)
                elif is_modified and reset_on_change and curr_val != default_val:
                    updated_fields[field_name] = default_val
                    fields_changed = True
                    fields_to_reset.append(field_name)

            if fields_changed:
                if is_modified and fields_to_reset:
                    reset_msg = ", ".join(fields_to_reset)
                    new_justification = f"File modified, pending re-audit (fields reset: {reset_msg})"
                    self.repository.workspace.update_manual_fields(filepath, updated_fields, new_justification)
                else:
                    self.repository.workspace.update_manual_fields(filepath, updated_fields, justification)
