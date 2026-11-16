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
