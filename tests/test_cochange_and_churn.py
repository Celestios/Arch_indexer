import pytest
from pathlib import Path
from db.connection import DbConnection
from db.repository import Repository
from change_tracker.git_coupling import get_co_changed_files
from interface.tools.impact import handle_impact
from interface.tools.lookup import handle_lookup
from setup.initializer import initialize_workspace


def test_git_co_change_and_churn(tmp_path):
    root = initialize_workspace(tmp_path)
    db_conn = DbConnection(root / "arch.db")
    repo = Repository(db_conn)

    # 1. Insert co-change record directly
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO file_co_changes (filepath_a, filepath_b, co_change_count, frequency)
            VALUES
                ('src/parser.py', 'src/scip.proto', 24, 0.92)
        """)
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash, change_count)
            VALUES
                ('parser_func().', 'src/parser.py', 'Function', 'def parse()', '', 'h1', 5)
        """)

    # Verify get_co_changed_files
    co_files = get_co_changed_files(repo, "src/parser.py", min_frequency=0.20)
    assert len(co_files) == 1
    assert co_files[0]["filepath"] == "src/scip.proto"
    assert round(co_files[0]["frequency"], 2) == 0.92

    # Verify handle_impact surfaces co-change and churn hotspot
    impact_md = handle_impact("parser_func().", max_depth=1, repository=repo)
    assert "## Blast Radius for: `parser_func()`" in impact_md
    assert "High-Churn Hotspot" in impact_md
    assert "### ── Historical Git Co-Change Coupling" in impact_md
    assert "src/scip.proto" in impact_md
    assert "92.0% co-change" in impact_md

    # Verify handle_lookup surfaces stability
    lookup_md = handle_lookup("parser_func().", repository=repo)
    assert "High Churn (5 modifications)" in lookup_md

    db_conn.close()
