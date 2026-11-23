import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from engines.scip.indexers import index_dart


def test_index_dart_already_activated(tmp_path):
    # Setup dummy project with pubspec.yaml and existing package_config.json
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text("name: mycelium")
    pkg_cfg = tmp_path / ".dart_tool" / "package_config.json"
    pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
    pkg_cfg.write_text("{}")

    with patch("shutil.which", return_value="/path/to/dart"), \
         patch("subprocess.run") as mock_run, \
         patch("engines.scip.indexers.run_with_scroll", return_value=0) as mock_scroll, \
         patch("engines.scip.indexers._move_index_to_arch", return_value=tmp_path / ".arch" / "index_dart.scip") as mock_move:

        # Mock global list return showing scip_dart is active
        mock_list_res = MagicMock()
        mock_list_res.returncode = 0
        mock_list_res.stdout = "scip_dart 1.6.2\n"
        mock_run.return_value = mock_list_res

        res = index_dart(tmp_path)

        assert res is not None
        # Should have checked list, but NOT activated
        mock_run.assert_called_once_with(
            ["dart", "pub", "global", "list"],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, shell=pytest.approx(True) if sys.platform == "win32" else pytest.approx(False)
        )
        mock_scroll.assert_called_once_with(
            ["dart", "pub", "global", "run", "scip_dart", "."],
            cwd=str(tmp_path), shell=pytest.approx(True) if sys.platform == "win32" else pytest.approx(False)
        )


def test_index_dart_not_activated_success(tmp_path):
    # Setup dummy project with pubspec.yaml and existing package_config.json
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text("name: mycelium")
    pkg_cfg = tmp_path / ".dart_tool" / "package_config.json"
    pkg_cfg.parent.mkdir(parents=True, exist_ok=True)
    pkg_cfg.write_text("{}")

    with patch("shutil.which", return_value="/path/to/dart"), \
         patch("subprocess.run") as mock_run, \
         patch("engines.scip.indexers.run_with_scroll", return_value=0) as mock_scroll, \
         patch("engines.scip.indexers._move_index_to_arch", return_value=tmp_path / ".arch" / "index_dart.scip") as mock_move:

        # Mock global list showing other packages or empty
        mock_list_res = MagicMock()
        mock_list_res.returncode = 0
        mock_list_res.stdout = "other_package 1.0.0\n"

        # Mock global activate success
        mock_act_res = MagicMock()
        mock_act_res.returncode = 0

        mock_run.side_effect = [mock_list_res, mock_act_res]

        res = index_dart(tmp_path)

        assert res is not None
        assert mock_run.call_count == 2
        # First call: list
        mock_run.assert_any_call(
            ["dart", "pub", "global", "list"],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, shell=pytest.approx(True) if sys.platform == "win32" else pytest.approx(False)
        )
        # Second call: activate
        mock_run.assert_any_call(
            ["dart", "pub", "global", "activate", "scip_dart"],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, shell=pytest.approx(True) if sys.platform == "win32" else pytest.approx(False)
        )
        mock_scroll.assert_called_once_with(
            ["dart", "pub", "global", "run", "scip_dart", "."],
            cwd=str(tmp_path), shell=pytest.approx(True) if sys.platform == "win32" else pytest.approx(False)
        )
