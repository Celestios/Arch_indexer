import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from change_tracker.watcher_manager import WatcherManager, ProjectWatcher
from setup.initializer import initialize_workspace


@pytest.fixture(autouse=True)
def reset_manager():
    WatcherManager.reset_instance()
    yield
    WatcherManager.reset_instance()


def test_watcher_manager_ensure_and_stop(tmp_path):
    proj = tmp_path / "proj1"
    initialize_workspace(proj)

    manager = WatcherManager.get_instance()

    with patch.object(ProjectWatcher, "start", return_value=True) as mock_start, \
         patch.object(ProjectWatcher, "stop") as mock_stop:
        # Ensure watcher starts
        ok = manager.ensure_watcher(proj)
        assert ok is True
        assert manager.is_watching(proj) is True
        mock_start.assert_called_once()

        # Duplicate ensure doesn't start again
        ok2 = manager.ensure_watcher(proj)
        assert ok2 is True
        assert mock_start.call_count == 1

        # Stop watcher
        stopped = manager.stop_watcher(proj)
        assert stopped is True
        assert manager.is_watching(proj) is False
        mock_stop.assert_called_once()


def test_watcher_manager_stop_all(tmp_path):
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    initialize_workspace(p1)
    initialize_workspace(p2)

    manager = WatcherManager.get_instance()

    with patch.object(ProjectWatcher, "start", return_value=True), \
         patch.object(ProjectWatcher, "stop") as mock_stop:
        manager.ensure_watcher(p1)
        manager.ensure_watcher(p2)
        assert len(manager._watchers) == 2

        manager.stop_all()
        assert len(manager._watchers) == 0
        assert mock_stop.call_count == 2


def test_hybrid_scip_gate_and_crash_persistence(tmp_path):
    proj = tmp_path / "proj_gate"
    initialize_workspace(proj)
    sample = proj / "a.py"
    sample.write_text("def foo():\n    return 1\n", encoding="utf-8")

    w = ProjectWatcher(proj, debounce=0.1, scip_score_threshold=3500, scip_max_age=9000.0)
    with w._lock:
        w._pending = True
        w._first_trigger = 100.0
        w._last_trigger = 100.0
        w._changed_files.add(sample)
        w._line_changes["a.py"] = 3
        w._ast_changed.add("a.py")
        w._save_pending_state_locked()

        # Score = 5*1 + 1*3 + 10*1 = 18 < 3500 -> should NOT trigger at t=101
        assert w._should_trigger_scip_locked(101.0) is False
        # Should trigger at max_age (2.5h = 9000s)
        assert w._should_trigger_scip_locked(100.0 + 9000.0) is True

        # 30-file / 2000-line refactor (~2450) still holds below 3500
        for i in range(29):
            fp = f"f{i}.py"
            w._changed_files.add(proj / fp)
            w._ast_changed.add(fp)
        w._line_changes["a.py"] = 2000
        assert w._should_trigger_scip_locked(101.0) is False

        # Massive refactor pushes score >= 3500 -> triggers after debounce
        w._line_changes["a.py"] = 3200  # 5*30 + 3200 + 10*30 = 3650 >= 3500
        assert w._should_trigger_scip_locked(101.0) is True

    # Simulate crash recovery: new watcher loads .arch/scip_pending.json
    w2 = ProjectWatcher(proj, debounce=0.1, scip_score_threshold=3500, scip_max_age=9000.0)
    w2._load_pending_state()
    assert w2.has_pending_scip() is True

    # If SCIP fails, pending state must remain persisted
    with patch.object(w2, "_run_scip_reindex", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            w2.flush_pending()
    assert (proj / ".arch" / "scip_pending.json").exists()

    # On success, pending state is cleared
    with patch.object(w2, "_run_scip_reindex") as mock_run:
        assert w2.flush_pending() is True
        mock_run.assert_called_once()
    assert w2.has_pending_scip() is False
    assert not (proj / ".arch" / "scip_pending.json").exists()


def test_watcher_manager_flush_and_clear_pending(tmp_path):
    proj = tmp_path / "proj_flush"
    initialize_workspace(proj)
    manager = WatcherManager.get_instance()

    with patch.object(ProjectWatcher, "start", return_value=True), \
         patch.object(ProjectWatcher, "stop"):
        manager.ensure_watcher(proj)
        watcher = manager._watchers[str(proj.resolve()).replace("\\", "/")]
        with watcher._lock:
            watcher._changed_files.add(proj / "x.py")
            watcher._pending = True
        assert watcher.has_pending_scip() is True

        with patch.object(watcher, "_run_scip_reindex") as mock_run:
            assert manager.flush_pending(proj) is True
            mock_run.assert_called_once()
        assert watcher.has_pending_scip() is False

        with watcher._lock:
            watcher._changed_files.add(proj / "y.py")
            watcher._pending = True
        manager.clear_pending(proj, {"y.py"})
        assert watcher.has_pending_scip() is False
