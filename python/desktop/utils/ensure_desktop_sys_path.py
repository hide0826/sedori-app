#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desktop / python ルートを sys.path に冪等追加する（Track X Phase 2）。"""

from __future__ import annotations

import sys
from pathlib import Path


def get_desktop_root() -> str:
    """``python/desktop`` の絶対パスを返す。"""
    return str(Path(__file__).resolve().parents[1])


def get_python_root() -> str:
    """``python/``（desktop の親）の絶対パスを返す。"""
    return str(Path(get_desktop_root()).parent)


def ensure_desktop_on_sys_path() -> str:
    """``python/desktop`` を先頭、続けて ``python/`` を sys.path に冪等追加する。

    - desktop 先頭: ``utils`` / ``ui`` / ``database`` を desktop 側で解決
    - python 次点: ``from desktop.*`` パッケージ import を可能にする

    戻り値は desktop 絶対パス。
    """
    desktop_root = get_desktop_root()
    python_root = get_python_root()

    for path in (desktop_root, python_root):
        if path in sys.path:
            sys.path.remove(path)

    # insert 順に注意: 後から入れた方が先頭になる
    sys.path.insert(0, python_root)
    sys.path.insert(0, desktop_root)
    return desktop_root
