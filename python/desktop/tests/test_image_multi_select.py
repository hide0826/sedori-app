#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from desktop.ui.image_manager.support import (
    compute_image_multi_select,
    first_image_capture_dt,
    resolve_link_image_paths,
)


def test_left_click_adds_without_clearing():
    selected, anchor = compute_image_multi_select(
        clicked_index=2,
        selected={0},
        ctrl=False,
        shift=False,
        anchor=0,
    )
    assert selected == {0, 2}
    assert anchor == 2


def test_ctrl_click_toggles():
    selected, anchor = compute_image_multi_select(
        clicked_index=1,
        selected={0, 1, 2},
        ctrl=True,
        shift=False,
        anchor=2,
    )
    assert selected == {0, 2}
    assert anchor == 1

    selected, _ = compute_image_multi_select(
        clicked_index=3,
        selected={0, 2},
        ctrl=True,
        shift=False,
        anchor=1,
    )
    assert selected == {0, 2, 3}


def test_shift_click_selects_range():
    selected, anchor = compute_image_multi_select(
        clicked_index=4,
        selected={1},
        ctrl=False,
        shift=True,
        anchor=1,
    )
    assert selected == {1, 2, 3, 4}
    assert anchor == 1


def test_empty_click_clears():
    selected, anchor = compute_image_multi_select(
        clicked_index=None,
        selected={0, 1},
        ctrl=False,
        shift=False,
        anchor=0,
    )
    assert selected == set()
    assert anchor is None


class _Img:
    def __init__(self, dt=None):
        self.capture_dt = dt


def test_first_image_capture_dt_uses_first_not_later():
    from datetime import datetime
    first = _Img(datetime(2026, 9, 19, 20, 20, 51))
    later = _Img(datetime(2026, 9, 19, 20, 23, 32))
    assert first_image_capture_dt([first, later]) == first.capture_dt


def test_first_image_capture_dt_fallback_when_first_missing():
    from datetime import datetime
    later = _Img(datetime(2026, 9, 19, 20, 23, 32))
    assert first_image_capture_dt([_Img(None), later]) == later.capture_dt
    assert first_image_capture_dt([]) is None


def test_resolve_link_image_paths_uses_selected_subset():
    group = [
        r"D:\photos\a.jpg",
        r"D:\photos\b.jpg",
        r"D:\photos\c.jpg",
    ]
    selected = [r"D:\photos\b.jpg", r"D:\photos\c.jpg"]
    assert resolve_link_image_paths(selected, group) == selected


def test_resolve_link_image_paths_falls_back_to_group_when_empty():
    group = [r"D:\photos\a.jpg", r"D:\photos\b.jpg"]
    assert resolve_link_image_paths([], group) == group
    assert resolve_link_image_paths([r"D:\photos\other.jpg"], group) == group
