# Main Entry Point Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/main-entry-point.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `src/main.py` as the CLI entry point that wires together initializer, SCIP indexing, and auditor into a working pipeline, plus add tests for core components.

**Architecture:** Single `main.py` with subcommands (`init`, `index`, `audit`) that delegate to existing modules. Tests use pytest with tmp_path fixtures for isolation.

**Tech Stack:** Python 3.10+, pytest, duckdb

## Global Constraints

- Python 3.10+ required (pyproject.toml)
- All imports use relative style matching existing code (e.g., `from db.connection import ...`)
- No new dependencies beyond what pyproject.toml already declares
- Tests must pass with `.venv\Scripts\python -m pytest`

---

### Task 1: Create `src/main.py` entry point

**Covers:** Entry point wiring

**Files:**
- Create: `src/main.py`

**Interfaces:**
- Consumes: `setup.initializer.initialize_workspace`, `db.connection.DbConnection`, `db.repository.Repository`, `engines.scip_wrapper.ScipWrapper`
- Produces: `main()` function callable from `pyproject.toml` scripts

- [ ] **Step 1: Write `src/main.py`**

```python
import sys
import argparse
from pathlib import Path

from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from engines.scip_wrapper import ScipWrapper
from auditor.analyzer import Auditor


def cmd_init(args):
    """Initialize workspace: create .arch/, deploy config, setup DB schema."""
    project_root = Path(args.project_root).resolve()
    arch_dir = initialize_workspace(project_root)
    print(f"Workspace initialized at {arch_dir}")


def cmd_index(args):
    """Index a project: detect languages, run SCIP parser, ingest to DB."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"

    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    languages = ScipWrapper.detect_languages(project_root)
    if not languages:
        print("No supported languages detected (Dart, Rust).")
        return

    print(f"Detected languages: {', '.join(languages)}")

    for lang in languages:
        index_path = ScipWrapper.run_indexer(project_root, lang)
        if index_path:
            print(f"[{lang}] Index generated at {index_path}")
            parsed = ScipWrapper.parse_index(index_path)
            ScipWrapper.ingest_index(repository, parsed)
            print(f"[{lang}] {len(parsed['symbols'])} symbols ingested.")
        else:
            print(f"[{lang}] Indexing failed or skipped.", file=sys.stderr)

    db_conn.close()
    print("Indexing complete.")


def cmd_audit(args):
    """Run architectural compliance audit."""
    project_root = Path(args.project_root).resolve()
    arch_dir = project_root / ".arch"

    if not arch_dir.exists():
        print("Error: Workspace not initialized. Run 'arch init' first.", file=sys.stderr)
        sys.exit(1)

    db_conn = DbConnection(arch_dir / "arch.db")
    repository = Repository(db_conn)

    auditor = Auditor(repository, project_root)
    violations = auditor.run_audit()

    if violations:
        print(f"\nFound {len(violations)} violations:")
        for v in violations:
            print(f"  [{v['rule_id']}] {v['filepath']}:{v['line']} — {v['message']}")
    else:
        print("No violations found.")

    db_conn.close()


def main():
    parser = argparse.ArgumentParser(
        prog="arch",
        description="Arch-mcp: Agent-Native Code Intelligence & Compliance Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize workspace")
    init_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    init_parser.set_defaults(func=cmd_init)

    # index
    index_parser = subparsers.add_parser("index", help="Index project symbols")
    index_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    index_parser.set_defaults(func=cmd_index)

    # audit
    audit_parser = subparsers.add_parser("audit", help="Run compliance audit")
    audit_parser.add_argument("project_root", nargs="?", default=".", help="Project root directory")
    audit_parser.set_defaults(func=cmd_audit)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify import resolution**

Run: `.venv\Scripts\python -c "from src.main import main; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: add main.py CLI entry point with init/index/audit subcommands"
```

---

### Task 2: Add tests for initializer

**Covers:** Initializer workspace setup

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_initializer.py`

**Interfaces:**
- Consumes: `setup.initializer.initialize_workspace`
- Produces: pytest tests

- [ ] **Step 1: Create `tests/__init__.py`**

```python
```

- [ ] **Step 2: Write `tests/test_initializer.py`**

```python
from pathlib import Path
from setup.initializer import initialize_workspace


def test_initialize_creates_arch_dir(tmp_path):
    arch_dir = initialize_workspace(tmp_path)
    assert arch_dir.exists()
    assert (arch_dir / "config.json").exists()
    assert (arch_dir / "arch.db").exists()


def test_initialize_preserves_existing_config(tmp_path):
    arch_dir = tmp_path / ".arch"
    arch_dir.mkdir()
    config = arch_dir / "config.json"
    config.write_text('{"custom": true}')

    initialize_workspace(tmp_path)

    import json
    data = json.loads(config.read_text())
    assert data == {"custom": true}


def test_initialize_loads_compliance_rules(tmp_path):
    initialize_workspace(tmp_path)

    from db.connection import DbConnection
    from db.repository import Repository

    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repo = Repository(db_conn)

    with db_conn.session() as conn:
        res = conn.execute("SELECT COUNT(*) FROM compliance_rules").fetchone()
        assert res[0] > 0

    db_conn.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_initializer.py -v`

Expected: PASS (initializer already exists)

- [ ] **Step 4: Commit**

```bash
git add tests/__init__.py tests/test_initializer.py
git commit -m "test: add initializer workspace setup tests"
```

---

### Task 3: Add tests for auditor

**Covers:** Auditor violation detection

**Files:**
- Create: `tests/test_auditor.py`

**Interfaces:**
- Consumes: `auditor.analyzer.Auditor`, `db.connection.DbConnection`, `db.repository.Repository`
- Produces: pytest tests

- [ ] **Step 1: Write `tests/test_auditor.py`**

```python
import json
from pathlib import Path
from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor


def setup_workspace(tmp_path):
    """Helper to create a workspace and return (repository, config_path)."""
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def test_auditor_returns_empty_when_no_rules(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Overwrite config with empty rules
    config_path = root / ".arch" / "config.json"
    config_path.write_text("{}")

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()
    assert violations == []

    db_conn.close()


def test_auditor_loads_config(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    auditor = Auditor(repository, root)
    config = auditor.load_config()

    assert "lib" in config
    assert "automatic_fields" in config["lib"]

    db_conn.close()


def test_auditor_detects_violation(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Insert symbols that violate: Presentation -> Infrastructure
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('presentation_sym', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('infra_sym', 'lib/infra/client.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('presentation_sym', 'infra_sym', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    # Should detect Presentation -> Infrastructure violation
    assert len(violations) >= 1
    assert any("Presentation" in v["message"] and "Infrastructure" in v["message"]
               for v in violations)

    db_conn.close()


def test_auditor_no_false_positives(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Insert valid symbols: Domain -> Infrastructure (allowed)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('domain_sym', 'lib/core/model.dart', 'Class', null, null, null),
                ('infra_sym', 'lib/infra/client.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('domain_sym', 'infra_sym', 'Calls')
        """)

    auditor = Auditor(repository, root)
    violations = auditor.run_audit()

    # Domain -> Infrastructure should NOT be flagged
    assert len(violations) == 0

    db_conn.close()
```

- [ ] **Step 2: Run tests**

Run: `.venv\Scripts\python -m pytest tests/test_auditor.py -v`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_auditor.py
git commit -m "test: add auditor violation detection tests"
```

---

### Task 4: Add tests for main.py

**Covers:** CLI entry point

**Files:**
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: `main.main`, `main.cmd_init`, `main.cmd_index`, `main.cmd_audit`
- Produces: pytest tests

- [ ] **Step 1: Write `tests/test_main.py`**

```python
import sys
from pathlib import Path
from unittest.mock import patch
from main import main, cmd_init, cmd_index, cmd_audit


def test_main_no_args(capsys):
    """main() with no args prints help and exits."""
    with patch("sys.argv", ["arch"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 1

    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "arch" in captured.out.lower()


def test_cmd_init_creates_workspace(tmp_path):
    """cmd_init creates .arch/ directory."""
    args = type("Args", (), {"project_root": str(tmp_path)})()
    cmd_init(args)

    assert (tmp_path / ".arch").exists()
    assert (tmp_path / ".arch" / "config.json").exists()
    assert (tmp_path / ".arch" / "arch.db").exists()


def test_cmd_audit_no_violations(tmp_path, capsys):
    """cmd_audit runs without error on empty workspace."""
    from setup.initializer import initialize_workspace
    initialize_workspace(tmp_path)

    args = type("Args", (), {"project_root": str(tmp_path)})()
    cmd_audit(args)

    captured = capsys.readouterr()
    assert "No violations" in captured.out or "violations" in captured.out.lower()


def test_cmd_index_no_languages(tmp_path, capsys):
    """cmd_index handles project with no supported languages."""
    from setup.initializer import initialize_workspace
    initialize_workspace(tmp_path)

    args = type("Args", (), {"project_root": str(tmp_path)})()
    cmd_index(args)

    captured = capsys.readouterr()
    assert "No supported languages" in captured.out
```

- [ ] **Step 2: Run all tests**

Run: `.venv\Scripts\python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_main.py
git commit -m "test: add main.py CLI entry point tests"
```
