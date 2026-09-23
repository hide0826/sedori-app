# -*- coding: utf-8 -*-
"""ルートWebからデスクトップの services / database を import できるようにする。"""

from __future__ import annotations

import sys
from pathlib import Path

_DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
_PYTHON = _DESKTOP.parent


def ensure_desktop_importable() -> Path:
    for path in (str(_PYTHON), str(_DESKTOP)):
        if path in sys.path:
            sys.path.remove(path)
    sys.path.insert(0, str(_PYTHON))
    sys.path.insert(0, str(_DESKTOP))
    return _DESKTOP
