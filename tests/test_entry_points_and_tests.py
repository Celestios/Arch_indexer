import pytest
from db.connection import DbConnection
from db.repository import Repository
from interface.tools.impact import handle_impact
from interface.tools.lookup import handle_lookup
from setup.initializer import initialize_workspace


def test_test_coverage_and_entry_point_mapping(tmp_path):
    root = initialize_workspace(tmp_path)
    db_conn = DbConnection(root / "arch.db")
    repo = Repository(db_conn)

    # Call graph:
    # main() (in src/main.py) -> service_func() (in src/service.py)
    # test_service() (in tests/test_service.py) -> service_func()
    # service_func() -> helper_func() (in src/helper.py)
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('main().', 'src/main.py', 'Function', 'def main()', '', 'h1'),
                ('test_service().', 'tests/test_service.py', 'Function', 'def test_service()', '', 'h2'),
                ('service_func().', 'src/service.py', 'Function', 'def service_func()', '', 'h3'),
                ('helper_func().', 'src/helper.py', 'Function', 'def helper_func()', '', 'h4')
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES
                ('main().', 'service_func().', 'Calls'),
                ('test_service().', 'service_func().', 'Calls'),
                ('service_func().', 'helper_func().', 'Calls')
        """)

    # 1. Test handle_impact on helper_func()
    impact_md = handle_impact("helper_func().", max_depth=3, repository=repo)

    assert "## Blast Radius for: `helper_func()`" in impact_md
    assert "### ── Covered By Tests" in impact_md
    assert "test_service()" in impact_md
    assert "tests/test_service.py" in impact_md

    assert "### ── Root Entry Points Affected" in impact_md
    assert "main()" in impact_md
    assert "System Entry: `main()`" in impact_md

    # 2. Test handle_lookup on service_func()
    lookup_md = handle_lookup("service_func().", repository=repo)
    assert "## Code Symbol: `service_func()`" in lookup_md
    assert "### Covered By Tests" in lookup_md
    assert "test_service()" in lookup_md

    db_conn.close()
