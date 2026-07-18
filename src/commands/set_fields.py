import json
import sys

from auditor.analyzer import Auditor
from utils.session import workspace_session, resolve_filepath


def cmd_set_fields(args):
    """Sets manual fields for a file."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        try:
            fields = json.loads(args.fields_json)
        except Exception as e:
            print(f"Error: Invalid JSON fields payload: {e}", file=sys.stderr)
            sys.exit(1)

        filepath = resolve_filepath(repository, args.filepath)
        if not filepath:
            print(f"Error: File '{args.filepath}' is not registered in the database.", file=sys.stderr)
            sys.exit(1)

        file_info = repository.files.get_file(filepath)
        current_fields = {}
        if file_info.get("manual_fields"):
            try:
                current_fields = json.loads(file_info["manual_fields"])
            except Exception:
                pass

        for k, v in fields.items():
            if v is None:
                current_fields.pop(k, None)
            else:
                current_fields[k] = v

        repository.files.update_file_manual_fields(filepath, current_fields, args.justification)

        auditor = Auditor(repository, project_root)
        auditor.run_audit()

        print(f"Successfully updated manual fields for '{filepath}' to: {current_fields}.")
