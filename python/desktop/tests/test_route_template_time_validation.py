#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_template_time_validation の pytest（Track E route_summary Phase 0 安全網）。"""

from __future__ import annotations

from desktop.services.route_template_time_validation import (
    _time_filled,
    collect_route_template_time_issues,
)


def test_time_filled():
    assert _time_filled(None) is False
    assert _time_filled("") is False
    assert _time_filled("  ") is False
    assert _time_filled("-") is False
    assert _time_filled("none") is False
    assert _time_filled("nan") is False
    assert _time_filled("09:00") is True
    assert _time_filled("9:5") is True


def test_collect_issues_departure_return_pair():
    # 出発のみ
    issues = collect_route_template_time_issues(
        {"departure_time": "09:00", "return_time": ""},
        [],
    )
    assert any("出発時刻" in m and "帰宅時刻" in m for m in issues)

    # 帰宅のみ
    issues = collect_route_template_time_issues(
        {"departure_time": None, "return_time": "18:00"},
        [],
    )
    assert any("帰宅時刻" in m and "出発時刻" in m for m in issues)

    # 両方空
    issues = collect_route_template_time_issues({}, [])
    assert any("ともに未入力" in m for m in issues)

    # 両方あり → 全体警告なし（店舗なし）
    issues = collect_route_template_time_issues(
        {"departure_time": "09:00", "return_time": "18:00"},
        [],
    )
    assert issues == []


def test_collect_issues_store_in_out_mismatch():
    route = {"departure_time": "09:00", "return_time": "18:00"}
    visits = [
        {
            "store_code": "S001",
            "store_name": "テスト店",
            "store_in_time": "10:00",
            "store_out_time": "",
        },
        {
            "store_code": "S002",
            "store_name": "別店",
            "store_in_time": "",
            "store_out_time": "11:00",
        },
    ]
    issues = collect_route_template_time_issues(route, visits)
    joined = "\n".join(issues)
    assert "揃っていない店舗" in joined
    assert "テスト店" in joined
    assert "別店" in joined


def test_collect_issues_skips_non_store_codes():
    route = {"departure_time": "09:00", "return_time": "18:00"}
    visits = [
        {
            "store_code": "出発時刻",
            "store_name": "",
            "store_in_time": "09:00",
            "store_out_time": "",
        },
        {
            "store_code": "帰宅時刻",
            "store_in_time": "",
            "store_out_time": "18:00",
        },
    ]
    issues = collect_route_template_time_issues(route, visits)
    assert issues == []
