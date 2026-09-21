#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from desktop.utils.event_filter_safety import event_filter_guard, qevent_type_int


def test_event_filter_guard_allows_then_blocks():
    with event_filter_guard() as ok0:
        assert ok0 is True
        with event_filter_guard() as ok1:
            assert ok1 is True
            with event_filter_guard() as ok2:
                assert ok2 is True
                with event_filter_guard() as ok3:
                    assert ok3 is True
                    with event_filter_guard() as ok4:
                        assert ok4 is True
                        with event_filter_guard() as ok5:
                            assert ok5 is True
                            with event_filter_guard() as ok6:
                                assert ok6 is False


def test_event_filter_guard_resets_after_exit():
    with event_filter_guard() as ok:
        assert ok is True
    with event_filter_guard() as ok:
        assert ok is True


def test_qevent_type_int_invalid_returns_minus_one():
    assert qevent_type_int(None) == -1  # type: ignore[arg-type]
