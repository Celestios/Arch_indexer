import pytest
from pathlib import Path
from db.connection import DbConnection
from db.repository import Repository
from engines.scip.parser import ScipParser
from engines.scip.ingester import IndexIngester
from interface.formatters import format_lookup_symbol
import engines.scip_pb2 as scip_pb2


def test_format_lookup_symbol_mutation_and_reads():
    exact_symbol = ("test/foo().", "src/foo.py", "Function", "def foo()", "Doc", "hash1", 5, "test/ParentClass#")
    occurrences = [
        ("src/foo.py", 10, 10, 1),           # Definition (1)
        ("src/caller.py", 20, 20, 2 | 4),    # Reference (2) + WriteAccess (4) -> [Mutates]
        ("src/reader.py", 30, 30, 2 | 8),    # Reference (2) + ReadAccess (8) -> [Reads]
        ("tests/test_foo.py", 40, 40, 2 | 0x20), # Reference (2) + Test (32) -> [Test]
    ]
    edges = [("src/caller.py", "test/foo().", "Calls")]
    output = format_lookup_symbol(exact_symbol, occurrences, edges)

    assert "## Code Symbol: `test.foo()`" in output
    assert "- **Enclosing Symbol**: `test.ParentClass`" in output
    assert "Definition" in output
    assert "Reference [Mutates]" in output
    assert "Reference [Reads]" in output
    assert "Reference [Test]" in output


def test_format_lookup_symbol_unified_table():
    exact_symbol = (
        "db/base/BaseRepository#",
        "src/db/base.py",
        "Class",
        "class BaseRepository:",
        "Shared base class for all repository implementations.",
        "hash123",
        10,
        None,
        None,
        0,
        "db.base.BaseRepository"
    )
    occurrences = [
        ("src/db/base.py", 5, 25, 1),
        ("src/db/repository_compliance.py", 3, 3, 2 | 8),
        ("src/db/repository_compliance.py", 6, 6, 2 | 8),
        ("src/db/repository_edges.py", 4, 4, 2 | 8),
    ]
    edges = [
        ("db/repository_compliance/ComplianceRepository#", "db/base/BaseRepository#", "Implements"),
        ("db/repository_compliance/ComplianceRepository#", "db/base/BaseRepository#", "Calls"),
        ("db/base/BaseRepository#", "db/connection/DbConnection#", "Calls"),
    ]
    sym_fp_map = {
        "db/repository_compliance/ComplianceRepository#": "src/db/repository_compliance.py",
        "db/connection/DbConnection#": "src/db/connection.py",
    }
    output = format_lookup_symbol(exact_symbol, occurrences, edges, symbol_filepath_map=sym_fp_map)

    # 1. Unified header
    assert "### References & Call Graph" in output
    assert "| Location | Symbol / Scope | Relation | Role |" in output

    # 2. Merged occurrences and multiple relations for ComplianceRepository
    assert "| `src/db/repository_compliance.py:L3, L6` | `ComplianceRepository` | ← Calls, Implements | Reference [Reads] |" in output

    # 3. Definition row
    assert "| `src/db/base.py:L5-25` | `db.base.BaseRepository` | — | Definition |" in output

    # 4. Outgoing edge with direction arrow
    assert "| `src/db/connection.py` | `DbConnection` | → Calls | — |" in output

    # 5. File occurrence without edges
    assert "| `src/db/repository_edges.py:L4` | — | — | Reference [Reads] |" in output


def test_scip_primitives_ingestion(tmp_path):
    db_file = tmp_path / "test.db"
    db_conn = DbConnection(db_file)
    repo = Repository(db_conn)

    # 1. Upsert symbol with parent_symbol
    repo.graph.upsert_symbol(
        symbol="pkg/Bar#baz().",
        filepath="pkg/bar.py",
        kind="Method",
        signature="def baz()",
        docstring="Doc",
        body_hash="abc",
        parent_symbol="pkg/Bar#"
    )

    sym = repo.graph.get_symbol("pkg/Bar#baz().")
    assert sym is not None
    assert sym["parent_symbol"] == "pkg/Bar#"

    sym_exact = repo.graph.get_symbol("pkg/Bar#baz().")
    assert sym_exact is not None
    assert sym_exact["parent_symbol"] == "pkg/Bar#"

    # 2. Add diagnostics
    diags = [
        {
            "filepath": "pkg/bar.py",
            "symbol": "pkg/Bar#baz().",
            "line": 15,
            "col": 4,
            "severity": "Warning",
            "code": "W001",
            "message": "Unused variable",
            "tags": "Unnecessary"
        }
    ]
    repo.quality.record_diagnostics_bulk(diags)

    file_diags = repo.quality.get_diagnostics_for_file("pkg/bar.py")
    assert len(file_diags) == 1
    assert file_diags[0]["code"] == "W001"
    assert file_diags[0]["severity"] == "Warning"

    sym_diags = repo.quality.get_diagnostics_for_symbol("pkg/Bar#baz().")
    assert len(sym_diags) == 1
    assert sym_diags[0]["message"] == "Unused variable"

    # 3. Add Implements & TypeDefinition edges
    repo.graph.add_edge("pkg/Bar#", "pkg/IFoo#", "Implements", 1.0)
    repo.graph.add_edge("pkg/Bar#", "pkg/TypeFoo#", "TypeDefinition", 1.0)

    closure = repo.analytics.get_transitive_closure("pkg/IFoo#", max_depth=1)
    assert len(closure["upstream"]) == 1
    assert closure["upstream"][0]["symbol"] == "pkg/Bar#"
    assert closure["upstream"][0]["relation"] == "Implements"

    # 4. Cleanup diagnostics on delete
    repo.quality.delete_diagnostics_for_files(["pkg/bar.py"])
    assert len(repo.quality.get_diagnostics_for_file("pkg/bar.py")) == 0

    db_conn.close()


def test_clean_symbol_storage_and_querying(tmp_path):
    db_file = tmp_path / "test_clean_sym.db"
    db_conn = DbConnection(db_file)
    repo = Repository(db_conn)

    # 1. Upsert symbol without explicit clean_symbol -> auto-computes clean_symbol
    repo.graph.upsert_symbol(
        symbol="scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login().",
        filepath="src/auth/service.py",
        kind="Method",
        signature="def login(username, password)",
        docstring="Authenticates user",
        body_hash="hash1"
    )

    # Verify stored clean_symbol
    sym_by_raw = repo.graph.get_symbol("scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login().")
    assert sym_by_raw is not None
    assert sym_by_raw["clean_symbol"] == "src.auth.service.py.AuthService.login()"

    # 2. Querying by clean_symbol directly
    sym_by_clean = repo.graph.get_symbol("src.auth.service.py.AuthService.login()")
    assert sym_by_clean is not None
    assert sym_by_clean["symbol"] == "scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login()."

    # 3. get_symbol matches clean_symbol
    exact_by_clean = repo.graph.get_symbol("src.auth.service.py.AuthService.login()")
    assert exact_by_clean is not None
    assert exact_by_clean["symbol"] == "scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login()."
    assert exact_by_clean["clean_symbol"] == "src.auth.service.py.AuthService.login()"

    # 4. Search by keyword on clean_symbol
    results_kw = repo.graph.search_symbols("AuthService.login")
    assert len(results_kw) == 1
    assert results_kw[0]["symbol"] == "scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login()."

    # 5. Bulk upsert preserves and computes clean_symbol
    repo.graph.upsert_symbols_bulk([
        {
            "symbol": "rust-analyzer cargo my_crate 0.2.0 domain/user/User#",
            "filepath": "src/user.rs",
            "kind": "Struct",
            "signature": "struct User",
            "docstring": "User entity",
            "body_hash": "hash2"
        }
    ])
    user_sym = repo.graph.get_symbol("domain.user.User")
    assert user_sym is not None
    assert user_sym["clean_symbol"] == "domain.user.User"

    db_conn.close()


def test_scip_ingester_fuzzy_line_match(tmp_path):
    db_file = tmp_path / "test_fuzzy.db"
    db_conn = DbConnection(db_file)
    repo = Repository(db_conn)

    # 1. Pre-populate Tree-sitter declaration at line 10 (e.g. @override on line 10)
    repo.graph.upsert_symbol(
        symbol="lib.src.service.Service.handleRequest",
        clean_symbol="lib.src.service.Service.handleRequest",
        filepath="src/service.dart",
        kind="Method",
        signature="@override void handleRequest()",
        docstring="Handles client request",
        body_hash="ts_hash_123"
    )
    repo.graph.record_occurrences_bulk([
        {
            "symbol": "lib.src.service.Service.handleRequest",
            "filepath": "src/service.dart",
            "start_line": 10,
            "start_col": 0,
            "end_line": 10,
            "end_col": 20,
            "role": 1
        }
    ])

    # 2. SCIP index anchors definition on identifier at line 12 (offset of 2 lines)
    scip_sym_id = "scip-dart dart pkg 1.0.0 src/service.dart/Service#handleRequest()."
    parsed_data = {
        "symbols": {
            scip_sym_id: {
                "symbol": scip_sym_id,
                "filepath": "src/service.dart",
                "kind": "Method",
                "signature": "",
                "docstring": "",
                "code_block": None,
                "body_hash": None,
                "parent_symbol": "src/service.dart/Service#"
            }
        },
        "occurrences": [
            {
                "symbol": scip_sym_id,
                "filepath": "src/service.dart",
                "start_line": 12,
                "start_col": 2,
                "end_line": 12,
                "end_col": 15,
                "role": 1
            }
        ],
        "edges": []
    }

    IndexIngester.ingest_index(repo, parsed_data, project_root=None, force=False)

    # 3. Verify SCIP symbol merged Tree-sitter AST attributes
    merged = repo.graph.get_symbol(scip_sym_id)
    assert merged is not None
    assert merged["signature"] == "@override void handleRequest()"
    assert merged["body_hash"] == "ts_hash_123"

    # 4. Verify duplicate Tree-sitter symbol row was superseded and deleted
    old_ts = repo.graph.get_symbol("lib.src.service.Service.handleRequest")
    assert old_ts is None

    db_conn.close()


def test_scip_ingester_preserves_test_and_non_scip_files(tmp_path):
    db_file = tmp_path / "test_preserve.db"
    db_conn = DbConnection(db_file)
    repo = Repository(db_conn)

    # 1. Create files on disk and pre-populate Tree-sitter symbols in production file and test file
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "core.rs").write_text("pub fn core_run() {}", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_core.rs").write_text("pub fn test_basic_flow() {}", encoding="utf-8")

    repo.workspace.upsert_files_bulk([
        {"filepath": "src/core.rs", "language": "rust", "sha256": "h1"},
        {"filepath": "tests/test_core.rs", "language": "rust", "sha256": "h2"}
    ])
    repo.graph.upsert_symbol(
        symbol="tests.test_core.test_basic_flow",
        clean_symbol="tests.test_core.test_basic_flow",
        filepath="tests/test_core.rs",
        kind="Function",
        signature="fn test_basic_flow()",
        docstring="",
        body_hash="ts_test_hash"
    )

    # 2. SCIP index only contains src/core.rs (tests/ is not indexed by SCIP)
    scip_sym_id = "rust-analyzer cargo core 0.1.0 src/core.rs/core_run()."
    parsed_data = {
        "symbols": {
            scip_sym_id: {
                "symbol": scip_sym_id,
                "filepath": "src/core.rs",
                "kind": "Function",
                "signature": "fn core_run()",
                "docstring": "",
                "code_block": None,
                "body_hash": "scip_hash",
                "parent_symbol": None
            }
        },
        "occurrences": [
            {
                "symbol": scip_sym_id,
                "filepath": "src/core.rs",
                "start_line": 1,
                "start_col": 7,
                "end_line": 1,
                "end_col": 15,
                "role": 1
            }
        ],
        "edges": []
    }

    IndexIngester.ingest_index(repo, parsed_data, project_root=tmp_path, force=False)

    # 3. Verify tests/ symbol is still preserved in DB
    test_sym = repo.graph.get_symbol("tests.test_core.test_basic_flow")
    assert test_sym is not None
    assert test_sym["filepath"] == "tests/test_core.rs"

    db_conn.close()

