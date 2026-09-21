#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""アプリ全体の Qt イベントフィルタが互いに再入して RecursionError になるのを防ぐ。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from PySide6.QtCore import QEvent

_EVENT_FILTER_DEPTH = 0
_EVENT_FILTER_MAX_DEPTH = 6

try:
    QEVENT_SHOW = int(QEvent.Type.Show)
    QEVENT_WHEEL = int(QEvent.Type.Wheel)
    QEVENT_CONTEXT_MENU = int(QEvent.Type.ContextMenu)
except Exception:
    QEVENT_SHOW, QEVENT_WHEEL, QEVENT_CONTEXT_MENU = 17, 31, 82


def qevent_type_int(event: QEvent) -> int:
    """event.type() を int にする。enum の == 比較は PySide6 で再帰することがある。"""
    try:
        t = event.type()
        v = getattr(t, "value", t)
        return int(v)
    except Exception:
        return -1


@contextmanager
def event_filter_guard() -> Iterator[bool]:
    """True なら処理してよい。深すぎる再入なら False。"""
    global _EVENT_FILTER_DEPTH
    if _EVENT_FILTER_DEPTH >= _EVENT_FILTER_MAX_DEPTH:
        yield False
        return
    _EVENT_FILTER_DEPTH += 1
    try:
        yield True
    finally:
        _EVENT_FILTER_DEPTH -= 1
