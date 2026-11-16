"""Startup checks: folders must be usable before the server binds its port."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parent.parent


def test_prepare_directories_creates_folders(tmp_path):
    s = Settings(config_dir=tmp_path / "cfg" / "nested", temp_dir=tmp_path / "tmp")
    s.prepare_directories()
    assert s.config_dir.is_dir() and s.temp_dir.is_dir()
    assert list(s.temp_dir.iterdir()) == []  # write probe cleaned up


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_prepare_directories_reports_unwritable_folder(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        s = Settings(temp_dir=locked / "MediaLab", config_dir=tmp_path / "cfg")
        with pytest.raises(ValueError, match="MEDIALAB_TEMP_DIR"):
            s.prepare_directories()
    finally:
        locked.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_server_exits_before_binding_when_folder_unusable(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    env = {**os.environ, "MEDIALAB_TEMP_DIR": str(locked / "MediaLab"),
           "MEDIALAB_CONFIG_DIR": str(tmp_path / "cfg"), "MEDIALAB_PORT": "8799"}
    try:
        proc = subprocess.run([sys.executable, "-m", "app"], cwd=BACKEND, env=env,
                              capture_output=True, text=True, timeout=30)
    finally:
        locked.chmod(0o700)
    assert proc.returncode == 2
    assert "Cannot use the temporary folder" in proc.stderr
    assert "Uvicorn running" not in proc.stderr + proc.stdout
