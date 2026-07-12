#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KeepaService 純関数まわりの pytest（Track E Phase 0 安全網）。API 呼び出しなし。"""

from __future__ import annotations

from datetime import datetime, timezone

from desktop.services.keepa_service import KeepaService


def test_extract_latest_price_takes_last_positive():
    assert KeepaService._extract_latest_price([0, None, 12.5, 0, 99.0]) == 99.0
    assert KeepaService._extract_latest_price([10, 20, 30]) == 30.0


def test_extract_latest_price_empty_and_invalid():
    assert KeepaService._extract_latest_price(None) is None
    assert KeepaService._extract_latest_price([]) is None
    assert KeepaService._extract_latest_price([0, None, -1]) is None
    assert KeepaService._extract_latest_price(123) is None  # not iterable as series


def test_extract_latest_rank():
    assert KeepaService._extract_latest_rank([100, 0, 50]) == 50
    assert KeepaService._extract_latest_rank(None) is None
    assert KeepaService._extract_latest_rank([]) is None
    assert KeepaService._extract_latest_rank([0, -1]) is None


def test_offer_csv_numbers_list_and_string():
    assert KeepaService._offer_csv_numbers([1, 2, 3.5]) == [1.0, 2.0, 3.5]
    assert KeepaService._offer_csv_numbers("10,20,30") == [10.0, 20.0, 30.0]
    assert KeepaService._offer_csv_numbers("  ") is None
    assert KeepaService._offer_csv_numbers(None) is None
    assert KeepaService._offer_csv_numbers("1,x,3") is None
    assert KeepaService._offer_csv_numbers([]) is None


def test_offer_last_landed_list_price():
    # [時刻, 価格, 送料] — 単位は /100 前
    offer = {"offerCSV": [1000, 50000, 500]}
    assert KeepaService._offer_last_landed_list_price(offer) == 505.0

    # 複数トリプレットは末尾を採用
    offer2 = {"offerCSV": [1, 10000, 0, 2, 20000, 100]}
    assert KeepaService._offer_last_landed_list_price(offer2) == 201.0

    assert KeepaService._offer_last_landed_list_price({}) is None
    assert KeepaService._offer_last_landed_list_price({"offerCSV": [1, 2]}) is None


def test_maybe_scale_to_jpy_heuristic_without_reference():
    prices = {"new": 79.0, "used": 50.0}
    out = KeepaService._maybe_scale_to_jpy(prices, reference_jpy=None)
    assert out["new"] == 7900.0
    assert out["used"] == 5000.0


def test_maybe_scale_to_jpy_with_high_reference():
    prices = {"new": 79.0, "used": None}
    out = KeepaService._maybe_scale_to_jpy(prices, reference_jpy=7900.0)
    assert out["new"] == 7900.0
    assert out["used"] is None


def test_maybe_scale_to_jpy_leaves_normal_yen():
    prices = {"new": 3500.0, "used": 1200.0}
    out = KeepaService._maybe_scale_to_jpy(prices, reference_jpy=None)
    assert out == prices
    out2 = KeepaService._maybe_scale_to_jpy(prices, reference_jpy=3500.0)
    assert out2 == prices


def test_count_sales_drops_and_series_avg_range():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
    # 100 → 90 は 10% 改善（>=3%）→ 1 drop、90 → 89 は約1.1% → カウントしない
    rank = [(t0, 100.0), (t1, 90.0), (t2, 89.0)]
    assert KeepaService._count_sales_drops(rank) == 1
    assert KeepaService._count_sales_drops([(t0, 100.0)]) == 0

    avg, rng = KeepaService._series_avg_and_range([(t0, 10.0), (t1, 20.0), (t2, 30.0)])
    assert avg == 20.0
    assert rng == 20.0
    assert KeepaService._series_avg_and_range([]) == (None, None)


def test_condition_label_jp_and_to_float_or_none():
    assert KeepaService._condition_label_jp(1) == "新品"
    assert KeepaService._condition_label_jp(5) == "可"
    assert KeepaService._condition_label_jp(-1) == "不明"
    assert KeepaService._condition_label_jp(99) == "条件99"

    assert KeepaService._to_float_or_none("12.5") == 12.5
    assert KeepaService._to_float_or_none(None) is None
    assert KeepaService._to_float_or_none("x") is None
