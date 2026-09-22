# -*- coding: utf-8 -*-
"""rclone Drive push helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

PYTHON_DIR = Path(__file__).resolve().parents[2]
DESKTOP = PYTHON_DIR / "desktop"
for p in (str(DESKTOP), str(PYTHON_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from services.rclone_route_drive import (  # noqa: E402
    load_rclone_config,
    push_route_folder_to_drive,
    remote_dest,
)


def test_remote_dest():
    assert remote_dest("gdrive", "a/b", "box") == "gdrive:a/b/box"
    assert remote_dest("gdrive:", "", "box") == "gdrive:box"


def test_skipped_when_disabled(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"enabled": False, "remote": "gdrive"}), encoding="utf-8")
    folder = tmp_path / "20260922test"
    folder.mkdir()
    res = push_route_folder_to_drive(folder, config_path=cfg)
    assert res.status == "skipped"


def test_push_ok_mocked(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps(
            {
                "enabled": True,
                "remote": "gdrive",
                "remote_root": "仕入帳",
                "rclone_exe": "rclone",
                "timeout_sec": 30,
            }
        ),
        encoding="utf-8",
    )
    folder = tmp_path / "20260922test"
    folder.mkdir()
    (folder / "route.json").write_text("{}", encoding="utf-8")

    def fake_run(exe, args, timeout_sec=180):
        return 0, "ok", ""

    with patch("services.rclone_route_drive.find_rclone_exe", return_value="rclone"):
        with patch("services.rclone_route_drive._run", side_effect=fake_run):
            res = push_route_folder_to_drive(folder, config_path=cfg)
    assert res.status == "ok"
    assert "gdrive:仕入帳/20260922test" in res.remote_path


def test_load_env_override(tmp_path: Path, monkeypatch=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"enabled": False, "remote": "x"}), encoding="utf-8")
    import os

    os.environ["HIRIO_RCLONE_ENABLED"] = "1"
    os.environ["HIRIO_RCLONE_REMOTE"] = "gdrive"
    try:
        data = load_rclone_config(cfg)
        assert data["enabled"] is True
        assert data["remote"] == "gdrive"
    finally:
        os.environ.pop("HIRIO_RCLONE_ENABLED", None)
        os.environ.pop("HIRIO_RCLONE_REMOTE", None)


if __name__ == "__main__":
    import tempfile

    test_remote_dest()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        test_skipped_when_disabled(p / "a")
        test_push_ok_mocked(p / "b")
        test_load_env_override(p / "c")
    print("ok rclone_route_drive")
