#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_elapsed_days の pytest（Track A Phase 0 安全網）。"""

from __future__ import annotations

from datetime import date

from desktop.utils.purchase_elapsed_days import (
    calc_elapsed_days_for_purchase_record,
    format_elapsed_days_for_purchase_record,
    parse_display_date_for_elapsed_days,
)


def test_parse_display_date_for_elapsed_days():
    assert parse_display_date_for_elapsed_days("2025/01/10") == date(2025, 1, 10)
    assert parse_display_date_for_elapsed_days("") is None
    assert parse_display_date_for_elapsed_days(None) is None


def test_calc_prefers_listed_date(monkeypatch):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2025, 3, 15)

    monkeypatch.setattr("desktop.utils.purchase_elapsed_days.date", _FixedDate)

    days = calc_elapsed_days_for_purchase_record(
        {
            "出品日": "2025/03/01",
            "仕入れ日": "2025/01/01",
        }
    )
    assert days == 14


def test_calc_falls_back_to_purchase_date(monkeypatch):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2025, 3, 15)

    monkeypatch.setattr("desktop.utils.purchase_elapsed_days.date", _FixedDate)

    days = calc_elapsed_days_for_purchase_record({"仕入れ日": "2025/03/10"})
    assert days == 5


def test_calc_returns_none_without_dates():
    assert calc_elapsed_days_for_purchase_record({}) is None


def test_format_elapsed_days(monkeypatch):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2025, 3, 15)

    monkeypatch.setattr("desktop.utils.purchase_elapsed_days.date", _FixedDate)

    text, tip = format_elapsed_days_for_purchase_record({"出品日": "2025/03/01"})
    assert text == "14 日"
    assert "出品日" in tip

    text2, tip2 = format_elapsed_days_for_purchase_record({})
    assert text2 == "-"
    assert "未設定" in tip2
