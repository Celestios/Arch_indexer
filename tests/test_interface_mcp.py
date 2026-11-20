import sys
import json
from pathlib import Path

from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from auditor.analyzer import Auditor
from interface.project_registry import ProjectRegistry
import pytest


@pytest.fixture(autouse=True)
def clean_test_env(tmp_path, monkeypatch):
    global_dir = tmp_path / "global_arch"
    monkeypatch.setenv("ARCH_GLOBAL_DIR", str(global_dir))
    monkeypatch.delenv("ARCH_PROJECT_ROOT", raising=False)
    ProjectRegistry.reset_instance()
    yield
    monkeypatch.delenv("ARCH_PROJECT_ROOT", raising=False)
    ProjectRegistry.reset_instance()


def setup_workspace(tmp_path):
    """Helper to initialize workspace and return repo/connection."""
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def _patch_server_config(monkeypatch, root):
    """Patch server_config._resolved via the module that server.py actually imported."""
    import src.interface.server  # noqa: F401 – ensures sys.path + interface.server_config loaded
    server_config = sys.modules["interface.server_config"]
    monkeypatch.setattr(server_config, "_resolved", {"project_root": root})
    return server_config


def test_get_symbols_in_file(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('my_func', 'lib/ui/widget.dart', 'Method', 'my_func()', 'Docstring 1', null),
                ('other_func', 'lib/core/util.dart', 'Method', 'other_func()', 'Docstring 2', null)
        """)

    # Query existing file
    syms = repository.graph.get_symbols_in_file("lib/ui/widget.dart")
    assert len(syms) == 1
    assert syms[0]["symbol"] == "my_func"
    assert syms[0]["signature"] == "my_func()"
    assert syms[0]["docstring"] == "Docstring 1"

    # Query with alternative separator
    syms_win = repository.graph.get_symbols_in_file("lib\\ui\\widget.dart")
    assert len(syms_win) == 1
    assert syms_win[0]["symbol"] == "my_func"

    # Query non-existent file
    syms_none = repository.graph.get_symbols_in_file("lib/ui/none.dart")
    assert len(syms_none) == 0

    db_conn.close()


def test_get_transitive_closure(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('A', 'B', 'Calls'),
                ('B', 'C', 'Calls'),
                ('C', 'D', 'Calls'),
                ('X', 'B', 'Calls')
        """)

    closure = repository.analytics.get_transitive_closure("B", max_depth=3)
    upstream = closure["upstream"]
    downstream = closure["downstream"]

    # Upstream of B should be A and X (direct, depth 1)
    assert any(u["symbol"] == "A" and u["depth"] == 1 for u in upstream)
    assert any(u["symbol"] == "X" and u["depth"] == 1 for u in upstream)

    # Downstream of B should be C (depth 1) and D (depth 2)
    assert any(d["symbol"] == "C" and d["depth"] == 1 for d in downstream)
    assert any(d["symbol"] == "D" and d["depth"] == 2 for d in downstream)

    db_conn.close()


def test_layer_aggregations(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('sym1', 'src/db/repo.py', 'Method', null, null, null),
                ('sym2', 'src/db/connection.py', 'Class', null, null, null),
                ('sym3', 'src/engines/scip.py', 'Method', null, null, null),
                ('sym4', 'src/main.py', 'Function', null, null, null)
        """)

    totals = repository.analytics.get_repo_totals()
    assert totals["symbols"] == 4
    
    kinds = repository.analytics.get_symbol_counts_by_kind()
    assert kinds["Method"] == 2
    assert kinds["Class"] == 1
    assert kinds["Function"] == 1

    prefixes = repository.analytics.get_symbols_by_file_prefix()
    assert prefixes["src/db/"] == 2
    assert prefixes["src/engines/"] == 1
    assert prefixes["src/"] == 1

    db_conn.close()


def test_auditor_filter(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    config = {
        "lib": {
            "automatic_fields": {
                "layer": {
                    "values": ["Presentation", "Infrastructure"],
                    "default": "Domain",
                    "assignment_rules": [
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
                        {"value": "Presentation", "conditions": {"path_prefix": "lib/other_ui"}},
                        {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
                    ],
                    "handler": "dependency_check",
                    "rules": [
                        {"source": "Presentation", "target": "Infrastructure", "message": "Presentation cannot call Infrastructure"}
                    ]
                }
            }
        }
    }
    with open(root / ".arch" / "config.json", "w") as f:
        json.dump(config, f)

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('ui_widget', 'lib/ui/widget.dart', 'Method', null, null, null),
                ('infra_client', 'lib/infra/client.dart', 'Method', null, null, null),
                ('other_ui', 'lib/other_ui/widget.dart', 'Method', null, null, null),
                ('infra_other', 'lib/infra/other.dart', 'Method', null, null, null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('ui_widget', 'infra_client', 'Calls'),
                ('other_ui', 'infra_other', 'Calls')
        """)

    auditor = Auditor(repository, root)
    
    # Audit only lib/ui/
    violations_filtered = auditor.run_audit(filepath_filter="lib/ui/")
    assert len(violations_filtered) == 1
    assert violations_filtered[0]["symbol"] == "ui_widget"

    # Audit everything
    violations_all = auditor.run_audit()
    assert len(violations_all) == 2

    db_conn.close()


def test_mcp_tools_lookup(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)

    import src.interface.server as mcp_server

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('my_service', 'src/service.py', 'Class', 'class MyService', 'Service docstring', null),
                ('my_helper', 'src/helper.py', 'Function', 'def my_helper()', 'Helper docstring', null)
        """)
        conn.execute("""
            INSERT INTO files (filepath, sha256, language)
            VALUES ('src/service.py', 'hash123', 'python')
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('caller_sym', 'my_service', 'Calls'),
                   ('my_service', 'callee_sym', 'Calls')
        """)

    # 1. Exact symbol match
    out_exact = mcp_server.lookup("my_service")
    assert "Symbol:" in out_exact
    assert "my_service" in out_exact
    assert "class MyService" in out_exact
    assert "caller_sym" in out_exact
    assert "callee_sym" in out_exact

    # 2. File match
    out_file = mcp_server.lookup("src/service.py")
    assert "File Module:" in out_file or "service.py" in out_file

    # 3. Keyword fallback
    out_kw = mcp_server.lookup("helper")
    assert "my_helper" in out_kw

    # 4. Unknown target
    out_none = mcp_server.lookup("non_existent_symbol_xyz")
    assert "No files or symbols matched" in out_none

    db_conn.close()


def test_mcp_tools_context(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)

    import src.interface.server as mcp_server

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('class_sym', 'lib/ui/widget.dart', 'Class', 'class Widget', 'A widget class', null),
                ('method_sym', 'lib/ui/widget.dart', 'Method', 'def draw()', 'Draws the widget', null)
        """)
        conn.execute("""
            INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
            VALUES
                ('class_sym', 'lib/ui/widget.dart', 10, 1, 20, 1, 1),
                ('method_sym', 'lib/ui/widget.dart', 15, 1, 18, 1, 1)
        """)

    # Test context tool with single string
    out = mcp_server.context("lib/ui/widget.dart")
    assert "## File Index: `lib/ui/widget.dart`" in out
    assert "class_sym" in out
    assert "[L10-20]" in out
    assert "method_sym" in out
    assert "[L15-18]" in out

    # Test context tool with list of strings
    out_multi = mcp_server.context(["lib/ui/widget.dart"])
    assert "class_sym" in out_multi

    # Test empty file
    out_empty = mcp_server.context("unindexed_file.py")
    assert "No indexed symbols found in file" in out_empty

    db_conn.close()


def test_mcp_tools_impact(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)

    import src.interface.server as mcp_server

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('A', 'B', 'Calls'),
                ('B', 'C', 'Calls')
        """)

    out = mcp_server.impact("B", max_depth=2)
    assert "## Blast Radius for: `B`" in out
    assert "A" in out
    assert "C" in out
    assert "Path: `A` ──> `B`" in out
    assert "Path: `B` ──> `C`" in out

    db_conn.close()


def test_mcp_tools_impact_class_vs_method(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)

    import src.interface.server as mcp_server

    with db_conn.session() as conn:
        # Register a class and its member methods
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('pkg/MyClass#', 'src/my_class.py', 'Class', 'class MyClass', 'A demo class', null),
                ('pkg/MyClass#__init__().', 'src/my_class.py', 'Constructor', 'def __init__(self)', null, null),
                ('pkg/MyClass#run().', 'src/my_class.py', 'Method', 'def run(self)', 'Runs the task', null),
                ('pkg/ExternalCaller#execute().', 'src/caller.py', 'Method', 'def execute()', null, null),
                ('pkg/SubsystemService#do_work().', 'src/service.py', 'Method', 'def do_work()', null, null)
        """)
        # ExternalCaller instantiates MyClass and calls run()
        # MyClass.run() calls SubsystemService.do_work()
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES 
                ('pkg/ExternalCaller#execute().', 'pkg/MyClass#__init__().', 'Calls'),
                ('pkg/ExternalCaller#execute().', 'pkg/MyClass#run().', 'Calls'),
                ('pkg/MyClass#run().', 'pkg/SubsystemService#do_work().', 'Calls')
        """)

    # 1. Querying the Class directly produces categorized semantic buckets & guidance
    out_class = mcp_server.impact("MyClass")
    assert "## Blast Radius for Class: `pkg.MyClass`" in out_class
    assert "Contextual Guidance" in out_class
    assert "To see specific blast radius for method edits, run `impact(\"pkg.MyClass.<method_name>\")`" in out_class
    assert "### ── Direct Usages (Instantiation & Type References)" in out_class
    assert "pkg.ExternalCaller.execute()" in out_class
    assert "[Instantiation]" in out_class
    assert "### ── Interface Surface (Exposed Callers)" in out_class
    assert "pkg.MyClass.run" in out_class
    assert "Called by `pkg.ExternalCaller.execute()`" in out_class
    assert "### ── Downstream Dependencies (Per Method)" in out_class
    assert "External Subsystems: `pkg.SubsystemService.do_work()`" in out_class

    # 2. Querying the Method directly produces deterministic upstream/downstream blast radius
    out_method = mcp_server.impact("MyClass.run")
    assert "## Blast Radius for: `pkg.MyClass.run()`" in out_method
    assert "### ── Upstream Callers" in out_method
    assert "pkg.ExternalCaller.execute()" in out_method
    assert "### ── Downstream Callees" in out_method
    assert "pkg.SubsystemService.do_work()" in out_method

    db_conn.close()


def test_mcp_tools_compile_context(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)

    import src.interface.server as mcp_server

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('root_sym', 'src/core.py', 'Class', 'class RootSym', 'Core root symbol', null),
                ('child_sym', 'src/child.py', 'Function', 'def child_fn()', 'Child function', null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('root_sym', 'child_sym', 'Calls')
        """)

    # Test compile_context tool
    out = mcp_server.compile_context("root_sym", radius=1, direction="downstream", resolution="signature")
    assert "# Dynamic Architectural Context Compilation" in out
    assert "root_sym" in out
    assert "child_sym" in out

    # Test invalid direction validation
    out_err_dir = mcp_server.compile_context("root_sym", direction="invalid_dir")
    assert "Error:" in out_err_dir

    # Test invalid resolution validation
    out_err_res = mcp_server.compile_context("root_sym", resolution="invalid_res")
    assert "Error:" in out_err_res

    db_conn.close()


def test_mcp_tools_audit(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)

    import src.interface.server as mcp_server

    # Insert a violation manually in DB
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO compliance_rules (rule_id, description, severity)
            VALUES ('rules_test', 'presentation ui constraint', 'WARNING')
        """)
        conn.execute("""
            INSERT INTO compliance_violations (violation_id, rule_id, symbol, filepath, line, message)
            VALUES ('vi_1', 'rules_test', 'ui_widget', 'lib/ui/widget.dart', 10, 'call violation')
        """)

    def mock_run_audit(self, filepath_filter=None):
        return [{
            "violation_id": "vi_1",
            "rule_id": "rules_test",
            "symbol": "ui_widget",
            "filepath": "lib/ui/widget.dart",
            "line": 10,
            "message": "call violation"
        }]
    
    monkeypatch.setattr("auditor.analyzer.Auditor.run_audit", mock_run_audit)

    out = mcp_server.audit()
    assert "## Compliance Audit" in out
    assert "1 finding(s)" in out or "1 violation(s)" in out
    assert "[rules_test]" in out
    assert "lib/ui/widget.dart:L10" in out
    assert "ui_widget" in out
    assert "call violation" in out

    db_conn.close()


def test_mcp_tools_database_missing(tmp_path, monkeypatch):
    import src.interface.server as mcp_server
    server_config = sys.modules["interface.server_config"]

    # Set DB_PATH to non-existent location
    non_existent = tmp_path / "missing_dir" / "missing.db"
    monkeypatch.setattr(server_config, "_resolved", {"project_root": tmp_path})
    monkeypatch.setattr(server_config, "get_db_path", lambda: non_existent)

    # All tools should return clean error string instead of crashing
    assert "database not found" in mcp_server.lookup("target").lower()
    assert "database not found" in mcp_server.context("lib/file.dart").lower()
    assert "database not found" in mcp_server.impact("symbol").lower()
    assert "database not found" in mcp_server.compile_context("symbol").lower()
    assert "database not found" in mcp_server.audit().lower()
    assert "database not found" in mcp_server.map().lower()
    assert "database not found" in mcp_server.update().lower()
    assert "database not found" in mcp_server.graph().lower()


def test_mcp_tool_registered_names():
    import src.interface.server as mcp_server
    tools = getattr(mcp_server.mcp, "tools", [])
    assert "update" in tools
    assert "graph" in tools
    assert "reindex" not in tools
    assert "index" not in tools
    assert "projects" not in tools
    assert "register_project" not in tools
    assert "unregister_project" not in tools


def test_mcp_tools_update(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)
    import src.interface.server as mcp_server

    res = mcp_server.update()
    assert "## Workspace Update" in res


def test_mcp_tools_map(tmp_path, monkeypatch):
    repository, db_conn, root = setup_workspace(tmp_path)
    _patch_server_config(monkeypatch, root)
    import src.interface.server as mcp_server

    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO files (filepath, sha256, language, status, manual_status)
            VALUES
                ('src/db/connection.py', 'hash1', 'python', 'COMPLIANT', 'COMPLIANT'),
                ('src/auditor/analyzer.py', 'hash2', 'python', 'COMPLIANT', 'COMPLIANT'),
                ('tests/test_db.py', 'hash3', 'python', 'COMPLIANT', 'COMPLIANT')
        """)
        conn.execute("""
            INSERT INTO symbols (symbol, clean_symbol, filepath, kind, signature, parent_symbol)
            VALUES
                ('db.connection.connect', 'connect', 'src/db/connection.py', 'Function', 'connect()', null),
                ('auditor.analyzer.Auditor', 'Auditor', 'src/auditor/analyzer.py', 'Class', 'class Auditor', null),
                ('auditor.analyzer.Auditor.run', 'Auditor.run', 'src/auditor/analyzer.py', 'Method', 'run(self)', 'auditor.analyzer.Auditor'),
                ('tests.test_db.test_conn', 'test_conn', 'tests/test_db.py', 'Function', 'test_conn()', null),
                ('builtins.str', 'str', null, 'Class', 'class str', null)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation, weight)
            VALUES
                ('auditor.analyzer.Auditor.run', 'db.connection.connect', 'Calls', 5.0),
                ('tests.test_db.test_conn', 'db.connection.connect', 'Calls', 2.0),
                ('auditor.analyzer.Auditor.run', 'builtins.str', 'Calls', 10.0)
        """)

    # 1. Default map call (folder level at root, external excluded)
    res_default = mcp_server.map()
    assert "## Repository Architectural Blueprint Map" in res_default
    assert "### Project Totals" in res_default
    assert "`src/`" in res_default
    assert "`tests/`" in res_default
    # External excluded by default
    assert "`external/`" not in res_default
    assert "`tests/` ──[2 calls]──> `src/`" in res_default or "`tests/` ──[2 calls]──>" in res_default

    # 2. Scoped map call on src/ at tree_depth=1
    res_src = mcp_server.map(path="src", tree_depth=1, detail_level="folder")
    assert "`src/db/`" in res_src
    assert "`src/auditor/`" in res_src
    assert "`tests/`" not in res_src
    assert "`src/auditor/` ──[5 calls]──> `src/db/`" in res_src

    # 3. File detail level on src/auditor
    res_file = mcp_server.map(path="src/auditor", detail_level="file")
    assert "`src/auditor/analyzer.py`" in res_file

    # 4. Multi-target query
    res_multi = mcp_server.map(targets=[
        {"path": "src", "tree_depth": 1, "detail_level": "folder"},
        {"path": "tests", "tree_depth": 0, "detail_level": "folder"}
    ])
    assert "`src/db/`" in res_multi
    assert "`src/auditor/`" in res_multi
    assert "`tests/`" in res_multi
    assert "`src/auditor/` ──[5 calls]──> `src/db/`" in res_multi

    # 5. External inclusion test
    res_ext = mcp_server.map(include_external=True)
    assert "`external/`" in res_ext
    assert "builtins.str" in res_ext or "str" in res_ext


def test_run_server_sse(monkeypatch):
    import src.interface.server as mcp_server
    called = {}

    def mock_run(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(mcp_server.mcp, "run", mock_run)
    mcp_server.run_server(port=8099)

    assert mcp_server.mcp.settings.port == 8099
    assert called["kwargs"].get("transport") == "sse"


def test_run_server_stdio(monkeypatch):
    import src.interface.server as mcp_server
    called = {}

    def mock_run(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(mcp_server.mcp, "run", mock_run)
    mcp_server.run_server(port=0)

    assert "transport" not in called["kwargs"]

