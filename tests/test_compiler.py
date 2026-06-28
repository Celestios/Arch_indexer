import json
from pathlib import Path
from setup.initializer import initialize_workspace
from db.connection import DbConnection
from db.repository import Repository
from auditor.compiler import ContextCompiler


def setup_workspace(tmp_path):
    """Helper to create a workspace and return (repository, db_conn, root)."""
    initialize_workspace(tmp_path)
    db_conn = DbConnection(tmp_path / ".arch" / "arch.db")
    repository = Repository(db_conn)
    return repository, db_conn, tmp_path


def test_compiler_bfs_traversal(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Insert test symbols and call graph edges
    # a -> b -> c
    # d -> b
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('sym_a', 'lib/a.dart', 'Function', 'void sym_a()', 'A docstring', 'hash_a'),
                ('sym_b', 'lib/b.dart', 'Function', 'void sym_b()', 'B docstring', 'hash_b'),
                ('sym_c', 'lib/c.dart', 'Function', 'void sym_c()', 'C docstring', 'hash_c'),
                ('sym_d', 'lib/d.dart', 'Function', 'void sym_d()', 'D docstring', 'hash_d')
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES
                ('sym_a', 'sym_b', 'Calls'),
                ('sym_b', 'sym_c', 'Calls'),
                ('sym_d', 'sym_b', 'Calls')
        """)

    compiler = ContextCompiler(repository, root)

    # 1. Downstream: a -> b -> c (radius 2)
    downstream_nodes = compiler.traverse_subgraph("sym_a", radius=2, direction="downstream")
    assert downstream_nodes == ["sym_a", "sym_b", "sym_c"]

    # 2. Downstream: a -> b (radius 1)
    downstream_nodes_r1 = compiler.traverse_subgraph("sym_a", radius=1, direction="downstream")
    assert downstream_nodes_r1 == ["sym_a", "sym_b"]

    # 3. Upstream: c <- b <- a/d (radius 2)
    upstream_nodes = compiler.traverse_subgraph("sym_c", radius=2, direction="upstream")
    # order of sibling nodes can vary, but b is at depth 1, and a & d are at depth 2
    assert upstream_nodes[0] == "sym_c"
    assert upstream_nodes[1] == "sym_b"
    assert set(upstream_nodes[2:]) == {"sym_a", "sym_d"}

    # 4. Both: b <- (a, d) and b -> c
    both_nodes = compiler.traverse_subgraph("sym_b", radius=1, direction="both")
    assert both_nodes[0] == "sym_b"
    assert set(both_nodes[1:]) == {"sym_a", "sym_d", "sym_c"}

    db_conn.close()


def test_compiler_code_extraction(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Create dummy source files
    file_a = root / "lib" / "a.dart"
    file_a.parent.mkdir(parents=True, exist_ok=True)
    file_a.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

    compiler = ContextCompiler(repository, root)

    # Extract lines 2 to 4
    snippet = compiler.extract_raw_code("lib/a.dart", start_line=2, end_line=4)
    assert snippet == "line 2\nline 3\nline 4"

    # Extract line 1 only
    snippet_single = compiler.extract_raw_code("lib/a.dart", start_line=1, end_line=1)
    assert snippet_single == "line 1"

    # Extract non-existent file
    snippet_missing = compiler.extract_raw_code("lib/non_existent.dart", start_line=1, end_line=5)
    assert "not found on disk" in snippet_missing

    db_conn.close()


def test_compiler_compiles_markdown_report(tmp_path):
    repository, db_conn, root = setup_workspace(tmp_path)

    # Write dummy source files
    file_a = root / "lib" / "a.dart"
    file_a.parent.mkdir(parents=True, exist_ok=True)
    file_a.write_text("void a() {\n  print('A');\n}\n", encoding="utf-8")

    file_b = root / "lib" / "b.dart"
    file_b.write_text("void b() {\n  print('B');\n}\n", encoding="utf-8")

    # Insert symbols, definition occurrences, and edges
    with db_conn.session() as conn:
        conn.execute("""
            INSERT INTO symbols (symbol, filepath, kind, signature, docstring, body_hash)
            VALUES
                ('sym_a', 'lib/a.dart', 'Function', 'void a()', 'A docstring', 'hash_a'),
                ('sym_b', 'lib/b.dart', 'Function', 'void b()', 'B docstring', 'hash_b')
        """)
        # Definition occurrence roles has bit 0 set (1)
        conn.execute("""
            INSERT INTO occurrences (symbol, filepath, start_line, start_col, end_line, end_col, role)
            VALUES
                ('sym_a', 'lib/a.dart', 1, 1, 3, 1, 1),
                ('sym_b', 'lib/b.dart', 1, 1, 3, 1, 1)
        """)
        conn.execute("""
            INSERT INTO edges (source, target, relation)
            VALUES ('sym_a', 'sym_b', 'Calls')
        """)

    compiler = ContextCompiler(repository, root)

    # 1. Compile with full resolution
    out_file = root / "compiled_context.md"
    md = compiler.compile(
        focal_symbol="sym_a",
        radius=1,
        direction="downstream",
        resolution="full",
        out_filepath=str(out_file)
    )

    # Verify compiled markdown content
    assert "# Dynamic Architectural Context Compilation" in md
    assert "- **Focal Target**: `sym_a`" in md
    assert "- **Search Direction**: `downstream`" in md
    assert "Active Code Block:" in md
    assert "void a() {" in md
    assert "void b() {" in md
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == md

    # 2. Compile with signature resolution (suppress neighbors code blocks)
    md_sig = compiler.compile(
        focal_symbol="sym_a",
        radius=1,
        direction="downstream",
        resolution="signature"
    )
    # Focal node code block must still be present
    assert "void a() {" in md_sig
    # Neighbor node code block must be suppressed
    assert "void b() {" not in md_sig
    assert "Signature resolution mode: active code block suppressed." in md_sig

    db_conn.close()
