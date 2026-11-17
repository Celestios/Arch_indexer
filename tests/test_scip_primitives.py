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
    repo.symbols.upsert_symbol(
        symbol="pkg/Bar#baz().",
        filepath="pkg/bar.py",
        kind="Method",
        signature="def baz()",
        docstring="Doc",
        body_hash="abc",
        parent_symbol="pkg/Bar#"
    )

    sym = repo.symbols.get_symbol("pkg/Bar#baz().")
    assert sym is not None
    assert sym["parent_symbol"] == "pkg/Bar#"

    sym_exact = repo.symbols.get_symbol_exact("pkg/Bar#baz().")
    assert sym_exact is not None
    assert sym_exact[7] == "pkg/Bar#"

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
    repo.symbols.add_diagnostics_bulk(diags)

    file_diags = repo.symbols.get_diagnostics_for_file("pkg/bar.py")
    assert len(file_diags) == 1
    assert file_diags[0]["code"] == "W001"
    assert file_diags[0]["severity"] == "Warning"

    sym_diags = repo.symbols.get_diagnostics_for_symbol("pkg/Bar#baz().")
    assert len(sym_diags) == 1
    assert sym_diags[0]["message"] == "Unused variable"

    # 3. Add Implements & TypeDefinition edges
    repo.edges.add_edge("pkg/Bar#", "pkg/IFoo#", "Implements", 1.0)
    repo.edges.add_edge("pkg/Bar#", "pkg/TypeFoo#", "TypeDefinition", 1.0)

    closure = repo.edges.get_transitive_closure("pkg/IFoo#", max_depth=1)
    assert len(closure["upstream"]) == 1
    assert closure["upstream"][0]["symbol"] == "pkg/Bar#"
    assert closure["upstream"][0]["relation"] == "Implements"

    # 4. Cleanup diagnostics on delete
    repo.symbols.delete_diagnostics_for_file("pkg/bar.py")
    assert len(repo.symbols.get_diagnostics_for_file("pkg/bar.py")) == 0

    db_conn.close()


def test_clean_symbol_storage_and_querying(tmp_path):
    db_file = tmp_path / "test_clean_sym.db"
    db_conn = DbConnection(db_file)
    repo = Repository(db_conn)

    # 1. Upsert symbol without explicit clean_symbol -> auto-computes clean_symbol
    repo.symbols.upsert_symbol(
        symbol="scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login().",
        filepath="src/auth/service.py",
        kind="Method",
        signature="def login(username, password)",
        docstring="Authenticates user",
        body_hash="hash1"
    )

    # Verify stored clean_symbol
    sym_by_raw = repo.symbols.get_symbol("scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login().")
    assert sym_by_raw is not None
    assert sym_by_raw["clean_symbol"] == "src.auth.service.py.AuthService.login()"

    # 2. Querying by clean_symbol directly
    sym_by_clean = repo.symbols.get_symbol("src.auth.service.py.AuthService.login()")
    assert sym_by_clean is not None
    assert sym_by_clean["symbol"] == "scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login()."

    # 3. get_symbol_exact matches clean_symbol
    exact_by_clean = repo.symbols.get_symbol_exact("src.auth.service.py.AuthService.login()")
    assert exact_by_clean is not None
    assert exact_by_clean[0] == "scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login()."
    assert exact_by_clean[10] == "src.auth.service.py.AuthService.login()"

    # 4. Search by keyword on clean_symbol
    results_kw = repo.symbols.search_symbols_keyword("AuthService.login")
    assert len(results_kw) == 1
    assert results_kw[0][0] == "scip-python python my_app 1.0.0 src/auth/service.py/AuthService#login()."

    # 5. Bulk upsert preserves and computes clean_symbol
    repo.symbols.upsert_symbols_bulk([
        {
            "symbol": "rust-analyzer cargo my_crate 0.2.0 domain/user/User#",
            "filepath": "src/user.rs",
            "kind": "Struct",
            "signature": "struct User",
            "docstring": "User entity",
            "body_hash": "hash2"
        }
    ])
    user_sym = repo.symbols.get_symbol("domain.user.User")
    assert user_sym is not None
    assert user_sym["clean_symbol"] == "domain.user.User"

    db_conn.close()
