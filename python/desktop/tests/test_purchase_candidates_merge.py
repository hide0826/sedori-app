#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from desktop.ui.product.purchase_edit_mixin import (
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
