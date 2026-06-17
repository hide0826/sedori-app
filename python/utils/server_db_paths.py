# -*- coding: utf-8 -*-
"""FastAPI 等 PySide6 非依存環境向け DB パス。"""

from __future__ import annotations

import sys
from pathlib import Path


def _desktop_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "desktop" / "data"


def is_recording_mode_without_pyside6() -> bool:
    try:
        from PySide6.QtCore import QSettings

        return bool(QSettings("HIRIO", "DesktopApp").value("recording/enabled", False, type=bool))
    except ImportError:
        pass

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\HIRIO\DesktopApp") as key:
                val, typ = winreg.QueryValueEx(key, "recording/enabled")
                if typ == winreg.REG_DWORD:
                    return bool(val)
                return str(val).lower() in ("1", "true", "yes")
        except OSError:
            pass
    return False


def get_hirio_db_path_for_api() -> str:
    """デスクトップと同じ DB を参照（デモモード時は recording/hirio.db）。"""
    data_dir = _desktop_data_dir()
    if is_recording_mode_without_pyside6():
        recording_db = data_dir / "recording" / "hirio.db"
        if recording_db.exists():
            return str(recording_db)
    return str(data_dir / "hirio.db")
