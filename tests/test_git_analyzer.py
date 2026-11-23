"""Unit tests for the centralized Git analyzer, composable history tool, audit summary, and impact wiring."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from engines.git_analyzer import (
    CommitRecord,
    _clean_numstat_path,
    analyze_archaeology,
    analyze_coupling,
    analyze_growth,
    analyze_hotspots,
    analyze_test_gaps,
    analyze_thrash,
    get_file_impact_telemetry,
    parse_git_history,
    run_history_analysis,
)
from interface.tools.audit import handle_audit
from interface.tools.history import handle_history
from interface.tools.impact import handle_impact
from interface.validators import validate_sections


def _make_fake_repo(symbols=None, edges=None, compliance_summary=None, violations=None):
    repo = MagicMock()
    symbols = symbols or []
    edges = edges or []
    repo.graph.get_all_symbols.return_value = symbols
    repo.graph.get_edges.return_value = edges
    repo.graph.get_symbols_for_files.side_effect = lambda fps: [
        s for s in symbols if s.get("filepath") in fps
    ]
    repo.graph.get_symbol.side_effect = lambda sid: next(
        (s for s in symbols if s["symbol"] == sid or s.get("clean_symbol") == sid), None
    )
    repo.graph.get_member_symbols.return_value = []
    repo.graph.get_symbols_by_ids.side_effect = lambda ids: {
        s["symbol"]: s for s in symbols if s["symbol"] in ids
    }
    repo.graph.search_symbols.return_value = []
    repo.workspace.get_file.return_value = None
    repo.workspace.get_all_files_metadata.return_value = {}
    repo.analytics.get_transitive_closure.return_value = {"upstream": [], "downstream": []}
    repo.analytics.get_compliance_summary.return_value = compliance_summary or {
        "total_files": 10,
        "compliant_files": 8,
        "violating_files": 2,
        "pending_audit": 1,
        "manual_overrides": 0,
        "total_violations": 3,
        "automatic_violations": 3,
        "manual_violations": 0,
        "by_severity": {"Error": 2, "Warning": 1},
        "by_rule": [
            {
                "rule_id": "lib_layer_ui_db",
                "severity": "Error",
                "description": "UI cannot call DB",
                "count": 2,
                "file_count": 1,
            }
        ],
        "hotspot_files": [{"filepath": "src/ui.py", "count": 2}],
    }
    repo.quality.get_violations.return_value = violations if violations is not None else []
    return repo


def test_clean_numstat_path_handles_renames():
    assert _clean_numstat_path("src/{old.py => new.py}") == "src/new.py"
    assert _clean_numstat_path("old/a.rs => new/b.rs") == "new/b.rs"
    assert _clean_numstat_path("rust/core/src/lib.rs") == "rust/core/src/lib.rs"


def test_validate_sections():
    ok, secs = validate_sections(None, has_target=False)
    assert ok and secs == ["hotspots", "coupling"]

    ok, secs = validate_sections(None, has_target=True)
    assert ok and secs == ["archaeology", "coupling"]

    ok, secs = validate_sections("hotspots, thrash, hotspots")
    assert ok and secs == ["hotspots", "thrash"]

    ok, err = validate_sections(["hotspots", "bogus"])
    assert not ok and "bogus" in err


def test_parse_git_history_single_pass(tmp_path):
    (tmp_path / ".git").mkdir()
    sample_stdout = (
        "__ARCH_COMMIT__aaa111\x1f1700000100\x1ffix routing crash\n"
        "12\t4\tsrc/router.py\n"
        "2\t1\tsrc/bridge.py\n"
        "__ARCH_COMMIT__bbb222\x1f1700000000\x1frevert bad patch\n"
        "5\t18\tsrc/{old_router.py => router.py}\n"
    )
    with patch("engines.git_analyzer._run_git", return_value=sample_stdout):
        commits = parse_git_history(tmp_path, commits=50)

    assert len(commits) == 2
    assert commits[0].is_fix_msg and not commits[0].is_revert
    assert commits[0].files["src/router.py"] == (12, 4)
    assert commits[1].is_revert
    assert commits[1].files["src/router.py"] == (5, 18)


def test_non_atomic_discount_and_hidden_vs_structural_coupling(tmp_path):
    for rel in (
        "src/api.rs", "src/client.dart", "src/core.py", "src/helper.py",
        "src/n1.py", "src/n2.py", "src/n3.py", "src/n4.py",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n")

    # 3 tight 2-file surgical commits pairing api.rs <-> client.dart (HIDDEN: no static edge)
    # 3 noisy 6-file mixed commits pairing core.py <-> helper.py (STRUCTURAL: has static edge)
    commits = [
        CommitRecord(f"h{i}", i, 1000 - i, "sync bridge", False, False, {"src/api.rs": (10, 2), "src/client.dart": (8, 1)})
        for i in range(3)
    ] + [
        CommitRecord(
            f"m{i}",
            3 + i,
            900 - i,
            "bundled wip",
            False,
            False,
            {
                "src/core.py": (5, 1),
                "src/helper.py": (3, 1),
                "src/n1.py": (1, 0),
                "src/n2.py": (1, 0),
                "src/n3.py": (1, 0),
                "src/n4.py": (1, 0),
            },
        )
        for i in range(3)
    ]

    symbols = [
        {"symbol": "core.fn", "filepath": "src/core.py", "kind": "Function", "connection_weight": 5},
        {"symbol": "helper.fn", "filepath": "src/helper.py", "kind": "Function", "connection_weight": 5},
        {"symbol": "api.fn", "filepath": "src/api.rs", "kind": "Function", "connection_weight": 2},
        {"symbol": "client.fn", "filepath": "src/client.dart", "kind": "Function", "connection_weight": 2},
    ]
    edges = [{"source": "core.fn", "target": "helper.fn", "relation": "Calls", "weight": 1.0}]
    repo = _make_fake_repo(symbols=symbols, edges=edges)

    res = analyze_coupling(commits, repo, tmp_path, limit=20)
    items = res["items"]
    assert items
    top = items[0]
    assert {top["file_a"], top["file_b"]} == {"src/api.rs", "src/client.dart"}
    assert top["coupling_type"] == "HIDDEN"
    assert top["weighted_score"] == 3.0

    struct_pair = next(x for x in items if {x["file_a"], x["file_b"]} == {"src/core.py", "src/helper.py"})
    assert struct_pair["coupling_type"] == "STRUCTURAL"
    assert struct_pair["weighted_score"] < top["weighted_score"]


def test_hotspots_thrash_growth_and_test_gap(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/engine.py").write_text("def run():\n    return 1\n" * 20)
    (tmp_path / "src/util.py").write_text("def helper():\n    return 2\n" * 5)

    commits = [
        CommitRecord("c0", 0, 1000, "fix loop", False, True, {"src/engine.py": (30, 28)}),
        CommitRecord("c1", 1, 990, "revert attempt", True, False, {"src/engine.py": (25, 24)}),
        CommitRecord("c2", 2, 980, "add logic", False, False, {"src/engine.py": (80, 10)}),
        CommitRecord("c3", 3, 970, "update util", False, False, {"src/util.py": (5, 0), "tests/test_util.py": (10, 0)}),
    ]
    symbols = [
        {"symbol": "engine.run", "filepath": "src/engine.py", "kind": "Function", "connection_weight": 12},
        {"symbol": "caller.a", "filepath": "src/util.py", "kind": "Function", "connection_weight": 1},
    ]
    edges = [{"source": "caller.a", "target": "engine.run", "relation": "Calls", "weight": 1.0}]
    repo = _make_fake_repo(symbols=symbols, edges=edges)

    hs = analyze_hotspots(commits, repo, tmp_path, limit=5)
    assert hs["items"][0]["filepath"] == "src/engine.py"
    assert hs["items"][0]["bursts"] >= 2

    th = analyze_thrash(commits, tmp_path, limit=5)
    assert th["items"][0]["filepath"] == "src/engine.py"
    assert th["items"][0]["reverts"] == 1

    gr = analyze_growth(commits, tmp_path, limit=5)
    assert gr["items"][0]["filepath"] == "src/engine.py"
    assert gr["items"][0]["net_growth"] == 73

    tg = analyze_test_gaps(commits, repo, tmp_path, limit=5)
    assert tg["items"][0]["filepath"] == "src/engine.py"
    assert tg["items"][0]["co_modified_tests"] == 0


def test_archaeology_for_symbol(tmp_path):
    (tmp_path / ".git").mkdir()
    symbols = [
        {
            "symbol": "mod.solve()",
            "clean_symbol": "mod.solve()",
            "filepath": "src/solver.py",
            "kind": "Function",
            "start_line": 10,
            "end_line": 25,
        }
    ]
    repo = _make_fake_repo(symbols=symbols)
    sample_l = (
        "__ARCH_ARCH__a1b2c3d\x1f2026-11-18\x1ffix clamp radius\n"
        "diff --git a/src/solver.py b/src/solver.py\n"
        "--- a/src/solver.py\n"
        "+++ b/src/solver.py\n"
        "@@ -12,1 +12,2 @@\n"
        "-    return r\n"
        "+    r = max(r, 0)\n"
        "+    return r\n"
    )
    with patch("engines.git_analyzer._run_git", return_value=sample_l):
        res = analyze_archaeology(repo, tmp_path, "mod.solve()", limit=5)

    assert res["target_kind"] == "symbol"
    assert res["line_range"] == "L10-25"
    assert len(res["items"]) == 1
    assert res["items"][0]["added"] == 2
    assert res["items"][0]["deleted"] == 1
    assert "fix" in res["items"][0]["tags"]


def test_history_runs_single_git_pass_for_multiple_sections(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("a = 1\n")
    repo = _make_fake_repo()

    fake_commits = [
        CommitRecord("c0", 0, 1000, "fix a", False, True, {"src/a.py": (20, 15)}),
        CommitRecord("c1", 1, 990, "tweak a", False, False, {"src/a.py": (18, 12)}),
    ]
    with patch("engines.git_analyzer.parse_git_history", return_value=fake_commits) as mock_parse:
        md = handle_history(
            repo,
            tmp_path,
            sections=["hotspots", "thrash", "coupling", "growth", "test_gap"],
        )
        assert mock_parse.call_count == 1
        assert "### Hotspots" in md
        assert "### Thrash" in md
        assert "### Coupling" in md
        assert "### Growth" in md
        assert "### Test Gaps" in md


def test_history_non_git_repo_graceful_fallback(tmp_path):
    repo = _make_fake_repo()
    with patch("engines.git_analyzer._run_git", return_value=None):
        md = handle_history(repo, tmp_path, sections=["hotspots"])
        assert "No Git repository detected" in md


def test_audit_summary_only_includes_error_severity(tmp_path):
    repo = _make_fake_repo()
    with patch("interface.tools.audit.Auditor") as mock_auditor:
        mock_auditor.return_value.run_audit.return_value = []
        out = handle_audit(repo, tmp_path, summary_only=True)
        assert "8/10 compliant (80.0%)" in out
        assert "Error: 2, Warning: 1" in out
        assert "`lib_layer_ui_db` [Error]" in out
        assert "Hotspot Files" in out


def test_impact_wires_live_git_hotspot_telemetry(tmp_path):
    symbols = [
        {"symbol": "mod.core()", "clean_symbol": "mod.core()", "filepath": "src/core.py", "kind": "Function", "change_count": 2}
    ]
    repo = _make_fake_repo(symbols=symbols)
    fake_telemetry = {
        "hotspot": {
            "filepath": "src/core.py",
            "risk_tier": "HIGH",
            "risk_score": 31.4,
            "touches": 8,
            "bursts": 3,
            "rework_pct": 72,
            "fan_in": 9,
            "max_complexity": 11,
        },
        "co_changes": [
            {
                "filepath": "src/bridge.rs",
                "co_commits": 5,
                "confidence_pct": 80,
                "lift": 4.2,
                "coupling_type": "HIDDEN",
            }
        ],
    }
    with patch("engines.git_analyzer.get_file_impact_telemetry", return_value=fake_telemetry):
        out = handle_impact("mod.core()", 2, repo, project_root=tmp_path)
        assert "File Hotspot Risk" in out
        assert "`HIGH`" in out
        assert "[HIDDEN] `src/bridge.rs`" in out
