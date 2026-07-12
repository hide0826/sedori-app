#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""condition_labels 純関数の pytest（Track B Phase 0 安全網）。"""

from __future__ import annotations

from desktop.services.condition_labels import (
    backfill_condition_label_in_record,
    condition_code_from_value,
    is_numeric_condition,
    normalize_condition_display,
)


def test_is_numeric_condition():
    assert is_numeric_condition(2) is True
    assert is_numeric_condition("3") is True
    assert is_numeric_condition("3.0") is True
    assert is_numeric_condition("中古(良い)") is False
    assert is_numeric_condition("") is False
    assert is_numeric_condition(None) is False


def test_condition_code_from_value():
    assert condition_code_from_value(2) == 2
    assert condition_code_from_value("3.0") == 3
    assert condition_code_from_value("中古(非常に良い)") == 2
    assert condition_code_from_value("新品") == 11
    assert condition_code_from_value("") is None
    assert condition_code_from_value("不明ラベル") is None


def test_normalize_condition_display():
    assert normalize_condition_display(2) == "中古(非常に良い)"
    assert normalize_condition_display("3") == "中古(良い)"
    assert normalize_condition_display("中古(可)") == "中古(可)"
    assert normalize_condition_display("") == ""
    assert normalize_condition_display("99") == "99"


def test_backfill_condition_label_in_record():
    rec = {"コンディション": "2"}
    backfill_condition_label_in_record(rec)
    assert rec["コンディション"] == "中古(非常に良い)"
    assert rec["condition_code"] == 2

    already = {"コンディション": "中古(良い)"}
    backfill_condition_label_in_record(already)
    assert already["コンディション"] == "中古(良い)"
    assert already["condition_code"] == 3
