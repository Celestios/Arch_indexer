import sys

from utils.session import workspace_session, resolve_filepath


def register(subparsers):
    p = subparsers.add_parser("set-status", help="Set manual AI logical compliance status for a file")
    p.add_argument("filepath", help="Filepath to the target file")
    p.add_argument("status", choices=["COMPLIANT", "VIOLATION_DETECTED"], help="Manual logical compliance status")
    p.add_argument("justification", nargs="?", default=None, help="Justification comment (required for VIOLATION_DETECTED)")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_set_status)


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

        repository.workspace.update_file_manual_status(filepath, status, args.justification)

        repository.quality.delete_violations(filepath=filepath, origin="manual")
        if status == "VIOLATION_DETECTED":
            from utils.violation_id import ViolationId
            violation_id = ViolationId.generate("manual_logical_audit", filepath, args.justification)

            repository.quality.add_violation(
                violation_id=violation_id,
                rule_id="logical_audit",
                symbol=None,
                filepath=filepath,
                line=1,
                message=args.justification,
                origin="manual"
            )

        print(f"Successfully updated manual status for '{filepath}' to '{status}'.")
