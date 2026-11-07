from auditor.analyzer import Auditor
from utils.session import workspace_session


def register(subparsers):
    p = subparsers.add_parser("audit", help="Run compliance audit")
    p.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    p.set_defaults(func=cmd_audit)


def cmd_audit(args):
    """Run architectural compliance audit."""
    with workspace_session(args) as (project_root, arch_dir, repository):
        auditor = Auditor(repository, project_root)
        violations = auditor.run_audit()

        if violations:
            print(f"\nFound {len(violations)} violations:")
            for v in violations:
                print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} - {v['message']}")
        else:
            print("No violations found.")
