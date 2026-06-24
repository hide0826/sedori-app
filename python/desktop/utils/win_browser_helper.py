#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows: 外部ブラウザを前面に出す（CSV/ZIP/Excel ドラッグ＆ドロップ用）。"""

from __future__ import annotations

import sys
from typing import Iterable, List, Optional, Sequence

_DEFAULT_EXCLUDE = ("hirio", "せどり業務統合", "仕入行の編集", "cursor")

# Win32 constants
_SW_RESTORE = 9
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_HWND_BOTTOM = 1


def _normalize_keywords(keywords: Iterable[str]) -> List[str]:
    return [str(k).strip().lower() for k in keywords if str(k).strip()]


def _window_title_matches(title: str, keywords: Sequence[str], excludes: Sequence[str]) -> bool:
    lowered = (title or "").lower()
    if not lowered:
        return False
    if any(ex in lowered for ex in excludes):
        return False
    return any(key in lowered for key in keywords)


def _user32():
    import ctypes

    return ctypes.windll.user32  # type: ignore[attr-defined]


def _window_title(hwnd: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        length = user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            return ""
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        return buf.value or ""
    except Exception:
        return ""


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

        user32 = _user32()
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found: List[int] = []

        def enum_cb(hwnd: wintypes.HWND, _: wintypes.LPARAM) -> wintypes.BOOL:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _window_title(int(hwnd))
            if _window_title_matches(title, keywords, excludes):
                found.append(int(hwnd))
            return True

        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return found
    except Exception:
        return []


def _force_foreground(hwnd: int) -> bool:
    """SetForegroundWindow の Windows 制限を回避して前面へ。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = _user32()
        if not user32.IsWindow(hwnd):
            return False

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)

        foreground = user32.GetForegroundWindow()
        if foreground == hwnd:
            user32.BringWindowToTop(hwnd)
            return True

        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()  # type: ignore[attr-defined]

        attached_fg = False
        attached_cur = False
        try:
            if foreground_thread and foreground_thread != target_thread:
                attached_fg = bool(user32.AttachThreadInput(foreground_thread, target_thread, True))
            if current_thread and current_thread != target_thread:
                attached_cur = bool(user32.AttachThreadInput(current_thread, target_thread, True))

            # フォーカス奪取制限の回避（Alt キー）
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 0x0002, 0)

            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            return user32.GetForegroundWindow() == hwnd
        finally:
            if attached_cur:
                user32.AttachThreadInput(current_thread, target_thread, False)
            if attached_fg:
                user32.AttachThreadInput(foreground_thread, target_thread, False)
    except Exception:
        return False


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

    ok = False
    for hwnd in handles:
        if _force_foreground(hwnd):
            ok = True
    return ok


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
        user32 = _user32()
        insert_after = _HWND_TOPMOST if topmost else _HWND_NOTOPMOST
        swp_flags = _SWP_NOSIZE | _SWP_NOMOVE | _SWP_SHOWWINDOW
        if not topmost:
            swp_flags |= _SWP_NOACTIVATE
        for hwnd in handles:
            user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, swp_flags)
        if topmost:
            _force_foreground(handles[0])
        return True
    except Exception:
        return False


def lower_window_to_back(hwnd: int) -> bool:
    """指定ウィンドウを Z 順の背面へ（最小化せず、ドラッグ元を維持）。"""
    if sys.platform != "win32":
        return False
    try:
        user32 = _user32()
        if not user32.IsWindow(hwnd):
            return False
        user32.SetWindowPos(
            hwnd,
            _HWND_BOTTOM,
            0,
            0,
            0,
            0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE,
        )
        return True
    except Exception:
        return False


def lower_qt_widget_to_back(widget) -> bool:
    """Qt ウィジェットのネイティブウィンドウを背面へ送る。"""
    if sys.platform != "win32" or widget is None:
        return False
    try:
        hwnd = int(widget.winId())
        return lower_window_to_back(hwnd)
    except Exception:
        return False


def raise_qt_widget(widget) -> bool:
    """Qt ウィジェットを通常の Z 順へ戻す（アクティブ化はしない）。"""
    if sys.platform != "win32" or widget is None:
        return False
    try:
        hwnd = int(widget.winId())
        user32 = _user32()
        if not user32.IsWindow(hwnd):
            return False
        user32.SetWindowPos(
            hwnd,
            _HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOSIZE | _SWP_NOMOVE | _SWP_NOACTIVATE,
        )
        widget.raise_()
        return True
    except Exception:
        return False
