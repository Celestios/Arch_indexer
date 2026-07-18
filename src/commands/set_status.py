import sys

from utils.session import workspace_session, resolve_filepath


def cmd_set_status(args):
    """Sets manual AI compliance status flag for a file."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        status = args.status.upper()
        if status not in ("COMPLIANT", "VIOLATION_DETECTED"):
            print(f"Error: Invalid manual compliance status choice: {args.status}. Allowed: COMPLIANT, VIOLATION_DETECTED.", file=sys.stderr)
            sys.exit(1)

        if status == "VIOLATION_DETECTED" and not args.justification:
            print("Error: Justification must be provided when flagging a file as VIOLATION_DETECTED.", file=sys.stderr)
            sys.exit(1)

        filepath = resolve_filepath(repository, args.filepath)
        if not filepath:
            print(f"Error: File '{args.filepath}' is not registered in the database.", file=sys.stderr)
            sys.exit(1)

        repository.files.update_file_manual_status(filepath, status, args.justification)

        repository.compliance.delete_manual_violations(filepath)
        if status == "VIOLATION_DETECTED":
            import hashlib
            violation_text = f"manual_logical_audit_{filepath}_{args.justification}"
            violation_id = hashlib.sha256(violation_text.encode("utf-8")).hexdigest()[:16]

            repository.compliance.add_violation(
                violation_id=violation_id,
                rule_id="logical_audit",
                symbol=None,
                filepath=filepath,
                line=1,
                message=args.justification,
                origin="manual"
            )

        print(f"Successfully updated manual status for '{filepath}' to '{status}'.")
