#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同コンディション最安追従ロジックの単体テスト。"""

from __future__ import annotations

from desktop.services.sp_api_follow_reprice import (
    compute_follow_price,
    resolve_tp_floor,
    tp_key_for_days,
)
from desktop.services.sp_api_offers import (
    min_same_condition_from_offers,
    parse_listing_condition_code,
)


def test_tp_key_for_days():
    assert tp_key_for_days(30) == "tp0"
    assert tp_key_for_days(150) == "tp1"
    assert tp_key_for_days(200) == "tp2"
    assert tp_key_for_days(300) == "tp3"


def test_resolve_tp_floor():
    row = {"tp0": 3000, "tp1": 2000, "tp2": 1500, "tp3": 1000}
    assert resolve_tp_floor(20, row) == 3000
    assert resolve_tp_floor(150, row) == 2000
    assert resolve_tp_floor(10, {}) is None


def test_early_match_min():
    r = compute_follow_price(price=3000, days=30, min_same=2500, tp_floor=2000)
    assert r["new_price"] == 2500
    assert r["action"] == "最安揃え"


def test_early_floor_at_tp():
    r = compute_follow_price(price=3000, days=30, min_same=1500, tp_floor=2000)
    assert r["new_price"] == 2000
    assert r["action"] == "TP下限"


def test_early_already_min():
    r = compute_follow_price(price=2500, days=40, min_same=2500, tp_floor=2000)
    assert r["new_price"] == 2500
    assert r["action"] == "維持"


def test_day_150_is_early():
    r = compute_follow_price(price=3000, days=150, min_same=2500, tp_floor=2000)
    assert r["action"] == "最安揃え"
    assert r["new_price"] == 2500


def test_late_chase_100_above_tp():
    r = compute_follow_price(
        price=3000,
        days=160,
        min_same=2500,
        tp_floor=1800,
        runs_per_day=3,
    )
    assert r["new_price"] == 2400
    assert r["action"] == "ライバル-100"


def test_late_chase_stops_at_tp():
    r = compute_follow_price(
        price=3000,
        days=160,
        min_same=1500,
        tp_floor=1800,
        runs_per_day=3,
    )
    assert r["new_price"] == 1800
    assert r["action"] == "ライバル-100"


def test_late_no_cheaper_steps_toward_tp():
    r = compute_follow_price(
        price=3000,
        days=160,
        min_same=4000,
        tp_floor=1800,
        runs_per_day=3,
    )
    assert r["new_price"] < 3000
    assert r["new_price"] >= 1800
    assert r["action"] == "TP接近"


def test_unknown_days_keep():
    r = compute_follow_price(price=2000, days=-1, min_same=1000, tp_floor=1500)
    assert r["new_price"] == 2000
    assert r["action"] == "維持"


def test_parse_listing_condition_code():
    assert parse_listing_condition_code(2) == 2
    assert parse_listing_condition_code("11") == 11
    assert parse_listing_condition_code("中古(非常に良い)") == 2
    assert parse_listing_condition_code("新品") == 11


def test_min_same_condition_excludes_self():
    body = {
        "payload": {
            "Offers": [
                {
                    "SellerId": "ME",
                    "SubCondition": "VeryGood",
                    "ListingPrice": {"Amount": 1000},
                    "Shipping": {"Amount": 0},
                },
                {
                    "SellerId": "OTHER",
                    "SubCondition": "VeryGood",
                    "ListingPrice": {"Amount": 1800},
                    "Shipping": {"Amount": 200},
                },
                {
                    "SellerId": "OTHER2",
                    "SubCondition": "Good",
                    "ListingPrice": {"Amount": 900},
                    "Shipping": {"Amount": 0},
                },
            ]
        }
    }
    assert min_same_condition_from_offers(body, wanted_sub="VeryGood", exclude_seller_id="ME") == 2000
