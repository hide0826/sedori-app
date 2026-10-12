#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime

from desktop.ui.product.purchase_edit_mixin import (
    PurchaseEditMixin,
    compact_purchase_image_columns,
    merge_datetime_purchase_candidates,
    remove_image_paths_from_records,
)


def test_merge_keeps_other_jans_and_puts_current_first():
    date_matches = [
        (0, {"SKU": "A", "JAN": "111", "仕入れ日": "2026/09/19"}),
        (0, {"SKU": "B", "JAN": "222", "仕入れ日": "2026/09/19"}),
        (1, {"SKU": "C", "JAN": "333", "仕入れ日": "2026/09/18"}),
    ]
    jan_matches = [
        (0, {"SKU": "B", "JAN": "222", "仕入れ日": "2026/09/19"}),
    ]
    merged = merge_datetime_purchase_candidates(date_matches, jan_matches)
    skus = [rec["SKU"] for _, rec in merged]
    assert skus[0] == "B"
    assert set(skus) == {"A", "B", "C"}


def test_merge_without_jan_keeps_date_order():
    date_matches = [
        (1, {"SKU": "C", "JAN": "333", "仕入れ日": "2026/09/18"}),
        (0, {"SKU": "A", "JAN": "111", "仕入れ日": "2026/09/19"}),
    ]
    merged = merge_datetime_purchase_candidates(date_matches, [])
    assert [rec["SKU"] for _, rec in merged] == ["A", "C"]


def test_remove_image_paths_leaves_other_sku_images():
    records = [
        {
            "SKU": "OLD",
            "JAN": "111",
            "画像1": r"D:\photos\keep.jpg",
            "画像2": r"D:\photos\move.jpg",
            "画像3": r"D:\photos\also.jpg",
            "画像4": "",
            "画像5": "",
            "画像6": "",
        },
        {
            "SKU": "NEW",
            "JAN": "222",
            "画像1": "",
            "画像2": "",
            "画像3": "",
            "画像4": "",
            "画像5": "",
            "画像6": "",
        },
    ]
    removed = remove_image_paths_from_records(
        [r"D:\photos\move.jpg"],
        records,
        keep_sku="NEW",
    )
    assert removed == 1
    assert records[0]["画像1"] == r"D:\photos\keep.jpg"
    assert records[0]["画像2"] == r"D:\photos\also.jpg"
    assert records[0]["画像3"] == ""
    compact_purchase_image_columns(records[1])
    assert records[1]["画像1"] == ""


def _candidate_host(records):
    class Host:
        purchase_all_records = records
        _normalize_jan_for_match = staticmethod(PurchaseEditMixin._normalize_jan_for_match)
        _normalize_asin_for_match = staticmethod(PurchaseEditMixin._normalize_asin_for_match)
        _extract_purchase_record_date = staticmethod(PurchaseEditMixin._extract_purchase_record_date)

    return Host()


def test_datetime_window_looks_back_one_month_and_can_go_older():
    """撮影日の過去31日は出し、それより前は past_days を広げたときだけ出す。"""
    host = _candidate_host(
        [
            {"SKU": "week", "JAN": "111", "仕入れ日": "2026/10/05"},
            {"SKU": "month", "JAN": "222", "仕入れ日": "2026/09/20"},
            {"SKU": "older", "JAN": "333", "仕入れ日": "2026/08/01"},
            {"SKU": "soon", "JAN": "444", "仕入れ日": "2026/10/17"},
            {"SKU": "later", "JAN": "555", "仕入れ日": "2026/10/25"},
        ]
    )
    base = datetime(2026, 10, 11, 14, 58, 28)

    month_skus = [
        rec["SKU"]
        for rec in PurchaseEditMixin.find_purchase_candidates_by_datetime(
            host, base, past_days=31, future_days=7
        )
    ]
    assert month_skus == ["week", "soon", "month"]

    older_skus = [
        rec["SKU"]
        for rec in PurchaseEditMixin.find_purchase_candidates_by_datetime(
            host, base, past_days=62, future_days=7
        )
    ]
    assert "older" not in older_skus

    wide_skus = [
        rec["SKU"]
        for rec in PurchaseEditMixin.find_purchase_candidates_by_datetime(
            host, base, past_days=93, future_days=7
        )
    ]
    assert "older" in wide_skus
    assert "later" not in wide_skus


def test_datetime_window_days_window_stays_symmetric():
    host = _candidate_host(
        [
            {"SKU": "near", "JAN": "111", "仕入れ日": "2026/10/08"},
            {"SKU": "far", "JAN": "222", "仕入れ日": "2026/09/20"},
        ]
    )
    base = datetime(2026, 10, 11)
    skus = [
        rec["SKU"]
        for rec in PurchaseEditMixin.find_purchase_candidates_by_datetime(
            host, base, days_window=7
        )
    ]
    assert skus == ["near"]
