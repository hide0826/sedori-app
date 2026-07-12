#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在庫店舗照合の pytest（Track B Phase 0 安全網）。"""

from __future__ import annotations

from services.inventory_store_matching import attach_route_date_to_store_visits
from services.route_matching_service import RouteMatchingService


def test_attach_route_date_prepends_date_to_time_only():
    visits = [
        {"store_code": "OF-01", "store_in_time": "10:30", "store_out_time": "11:45"},
    ]
    attach_route_date_to_store_visits({"route_date": "2025-01-15"}, visits)
    assert visits[0]["store_in_time"] == "2025-01-15 10:30:00"
    assert visits[0]["store_out_time"] == "2025-01-15 11:45:00"


def test_attach_route_date_skips_when_route_date_empty():
    visits = [{"store_code": "OF-01", "store_in_time": "10:30", "store_out_time": "11:45"}]
    attach_route_date_to_store_visits({"route_date": ""}, visits)
    assert visits[0]["store_in_time"] == "10:30"
    assert visits[0]["store_out_time"] == "11:45"


def test_attach_route_date_leaves_already_dated_timestamps():
    visits = [
        {
            "store_code": "OF-01",
            "store_in_time": "2025-01-15 10:30:00",
            "store_out_time": "2025-01-15 11:45:00",
        }
    ]
    attach_route_date_to_store_visits({"route_date": "2025-01-16"}, visits)
    assert visits[0]["store_in_time"] == "2025-01-15 10:30:00"
    assert visits[0]["store_out_time"] == "2025-01-15 11:45:00"


def test_match_store_auto_matched_when_time_and_success():
    """滞在時間内 + 仕入れ成功 → スコア 0.7 で auto_matched。"""
    matcher = RouteMatchingService()
    purchases = [
        {
            "仕入れ日": "2025-01-15 10:45:00",
            "仕入れ価格": 1000,
            "販売予定価格": 3000,
        }
    ]
    visits = [
        {
            "store_code": "OF-01",
            "store_in_time": "2025-01-15 10:00:00",
            "store_out_time": "2025-01-15 12:00:00",
            "purchase_success": True,
            "store_gross_profit": 2000,
        }
    ]
    results = matcher.match_store_code_by_time_and_profit(purchases, visits)
    assert len(results) == 1
    assert results[0]["match_status"] == "auto_matched"
    assert results[0]["matched_store_code"] == "OF-01"
    assert results[0]["match_confidence"] >= 0.5


def test_match_store_manual_review_when_no_time_overlap():
    matcher = RouteMatchingService()
    purchases = [
        {
            "仕入れ日": "2025-01-15 15:00:00",
            "仕入れ価格": 1000,
            "販売予定価格": 3000,
        }
    ]
    visits = [
        {
            "store_code": "OF-01",
            "store_in_time": "2025-01-15 10:00:00",
            "store_out_time": "2025-01-15 12:00:00",
            "purchase_success": False,
        },
        {
            "store_code": "KO-02",
            "store_in_time": "2025-01-15 13:00:00",
            "store_out_time": "2025-01-15 14:00:00",
            "purchase_success": True,
        },
    ]
    results = matcher.match_store_code_by_time_and_profit(purchases, visits)
    assert len(results) == 1
    assert results[0]["match_status"] == "manual_review_required"
    assert results[0]["matched_store_code"] is None
    assert "KO-02" in results[0]["candidate_store_codes"]


def test_safe_float_handles_commas_and_invalid():
    matcher = RouteMatchingService()
    assert matcher._safe_float("1,234") == 1234.0
    assert matcher._safe_float("") is None
    assert matcher._safe_float(None) is None
    assert matcher._safe_float("abc") is None
