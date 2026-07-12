#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_visit_normalize / route_utils の pytest（Track E route_summary Phase 0 安全網）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from desktop.services.route_visit_normalize import (
    _parse_visit_datetime,
    normalize_route_visits,
)
from _source_symbol_loader import load_module_functions

_ROUTE_UTILS = Path(__file__).resolve().parents[1] / "utils" / "route_utils.py"
_parse_route_from_folder_name = load_module_functions(
    _ROUTE_UTILS, ["_parse_route_from_folder_name"]
)["_parse_route_from_folder_name"]


def test_parse_visit_datetime():
    route_date = "2026-02-15"
    assert _parse_visit_datetime("2026-02-15 10:30:00", route_date) == datetime(
        2026, 2, 15, 10, 30, 0
    )
    assert _parse_visit_datetime("2026/02/15 10:30", route_date) == datetime(
        2026, 2, 15, 10, 30
    )
    assert _parse_visit_datetime("10:30", route_date) == datetime(2026, 2, 15, 10, 30, 0)
    assert _parse_visit_datetime(None, route_date) is None
    assert _parse_visit_datetime("", route_date) is None
    assert _parse_visit_datetime("not-a-time", route_date) is None


def test_normalize_route_visits_orders_by_in_time_and_stay():
    visits = [
        {
            "store_code": "S002",
            "store_name": "後の店",
            "visit_order": 1,
            "store_in_time": "11:00",
            "store_out_time": "11:30",
            "route_date": "2026-02-15",
        },
        {
            "store_code": "S001",
            "store_name": "先の店",
            "visit_order": 2,
            "store_in_time": "10:00",
            "store_out_time": "10:20",
            "route_date": "2026-02-15",
        },
    ]
    out = normalize_route_visits(visits, "2026-02-15")
    assert [v["store_code"] for v in out] == ["S001", "S002"]
    assert out[0]["visit_order"] == 1
    assert out[1]["visit_order"] == 2
    # 先の店: 10:00〜10:20 → 滞在 20 分
    assert out[0]["stay_duration"] == 20.0
    # 後の店: 前店 OUT(10:20) → IN(11:00) → 移動 40 分、滞在 30 分
    assert out[1]["travel_time_from_prev"] == 40.0
    assert out[1]["stay_duration"] == 30.0
    assert out[0]["travel_time_from_prev"] == 0.0


def test_parse_route_from_folder_name_variants():
    assert _parse_route_from_folder_name("20260215つくばルート") == (
        "2026-02-15",
        "つくばルート",
    )
    assert _parse_route_from_folder_name("20260215_つくばルート") == (
        "2026-02-15",
        "つくばルート",
    )
    assert _parse_route_from_folder_name("2026-02-15つくばルート") == (
        "2026-02-15",
        "つくばルート",
    )
    assert _parse_route_from_folder_name("2026_02_15_つくばルート") == (
        "2026-02-15",
        "つくばルート",
    )
    assert _parse_route_from_folder_name("") is None
    assert _parse_route_from_folder_name("つくばルート") is None
    assert _parse_route_from_folder_name("20260215") is None
