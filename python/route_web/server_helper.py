# -*- coding: utf-8 -*-
"""ルート時刻 Web (:8792) の起動ヘルパー。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from route_web import ROUTE_WEB_PORT

HEALTH_URL = f"http://127.0.0.1:{ROUTE_WEB_PORT}/health"


def is_route_web_up(timeout: float = 1.0) -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=timeout) as resp:
            return getattr(resp, "status", 200) == 200
    except (URLError, OSError, TimeoutError):
        return False


def python_dir() -> str:
    # .../python/route_web/server_helper.py -> .../python
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def ensure_route_web_running(wait_seconds: float = 8.0) -> Tuple[bool, str]:
    """
    ルート時刻 Web が動いていなければバックグラウンド起動する。
    Returns: (ok, message)
    """
    if is_route_web_up():
        return True, "already running"

    cwd = python_dir()
    creationflags = 0
    if sys.platform == "win32":
        # コンソール無しのバックグラウンド起動（デスクトップから）
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        subprocess.Popen(
            [sys.executable, "-m", "route_web"],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as exc:
        return False, f"起動失敗: {exc}"

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_route_web_up():
            return True, "started"
        time.sleep(0.25)
    return False, (
        f"起動タイムアウト。手動で start_route_web.bat を実行してください（port {ROUTE_WEB_PORT}）"
    )


def public_base_urls() -> list[str]:
    """スマホ向けに案内するベース URL 候補。"""
    return [
        f"http://houseserver:{ROUTE_WEB_PORT}",
        f"http://192.168.0.200:{ROUTE_WEB_PORT}",
        f"http://127.0.0.1:{ROUTE_WEB_PORT}",
    ]


def home_url(base: Optional[str] = None) -> str:
    """固定のルート一覧URL（スマホはこれをブックマーク）。"""
    root = (base or public_base_urls()[0]).rstrip("/")
    return f"{root}/"


def route_page_url(web_id: str, base: Optional[str] = None) -> str:
    root = (base or public_base_urls()[0]).rstrip("/")
    return f"{root}/route/{web_id}"
