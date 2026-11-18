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
