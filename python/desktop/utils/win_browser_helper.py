#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows: 外部ブラウザを前面に出す（CSVドラッグ＆ドロップ用）。"""

from __future__ import annotations

import sys
from typing import Iterable, List, Sequence

_DEFAULT_EXCLUDE = ("hirio", "せどり業務統合", "仕入行の編集", "cursor")


def _normalize_keywords(keywords: Iterable[str]) -> List[str]:
    return [str(k).strip().lower() for k in keywords if str(k).strip()]


def _window_title_matches(title: str, keywords: Sequence[str], excludes: Sequence[str]) -> bool:
    lowered = (title or "").lower()
    if not lowered:
        return False
    if any(ex in lowered for ex in excludes):
        return False
    return any(key in lowered for key in keywords)


def find_browser_window_handles(
    title_keywords: Iterable[str],
    *,
    exclude_keywords: Iterable[str] = _DEFAULT_EXCLUDE,
) -> List[int]:
    """タイトルにキーワードを含む可視ウィンドウの HWND 一覧（Windows のみ）。"""
    if sys.platform != "win32":
        return []

    keywords = _normalize_keywords(title_keywords)
    if not keywords:
        return []

    excludes = _normalize_keywords(exclude_keywords)

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found: List[int] = []

        def enum_cb(hwnd: wintypes.HWND, _: wintypes.LPARAM) -> wintypes.BOOL:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd) + 1
            if length <= 1:
                return True
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value or ""
            if _window_title_matches(title, keywords, excludes):
                found.append(int(hwnd))
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found
    except Exception:
        return []


def bring_browser_to_front(
    title_keywords: Iterable[str],
    *,
    exclude_keywords: Iterable[str] = _DEFAULT_EXCLUDE,
) -> bool:
    """マッチしたブラウザウィンドウを前面に出す。"""
    if sys.platform != "win32":
        return False

    handles = find_browser_window_handles(title_keywords, exclude_keywords=exclude_keywords)
    if not handles:
        return False

    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = handles[0]
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        return True
    except Exception:
        return False


def set_browser_topmost(
    title_keywords: Iterable[str],
    topmost: bool,
    *,
    exclude_keywords: Iterable[str] = _DEFAULT_EXCLUDE,
) -> bool:
    """マッチしたブラウザを一時的に最前面固定／解除する。"""
    if sys.platform != "win32":
        return False

    handles = find_browser_window_handles(title_keywords, exclude_keywords=exclude_keywords)
    if not handles:
        return False

    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        insert_after = -1 if topmost else -2  # HWND_TOPMOST / HWND_NOTOPMOST
        swp_flags = 0x0001 | 0x0002 | 0x0040  # NOSIZE | NOMOVE | SHOWWINDOW
        for hwnd in handles:
            user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, swp_flags)
        if topmost:
            user32.SetForegroundWindow(handles[0])
        return True
    except Exception:
        return False
