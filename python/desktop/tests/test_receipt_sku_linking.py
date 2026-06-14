#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from datetime import datetime

from desktop.services.receipt_sku_linking import (
    build_manual_candidate_entries,
    collect_link_skus_for_receipt,
    sort_receipts_for_bulk_matching,
)


def test_bulk_matching_respects_time_and_used_skus():
    purchase_records = [
        {"SKU": "SKU-A", "仕入れ日": "2024/06/06 09:00", "仕入先": "SS-18"},
        {"SKU": "SKU-B", "仕入れ日": "2024/06/06 09:30", "仕入先": "SS-18"},
        {"SKU": "SKU-C", "仕入れ日": "2024/06/06 10:30", "仕入先": "SS-18"},
    ]
    receipts = [
        {"id": 2, "store_code": "SS-18", "purchase_date": "2024/06/06", "purchase_time": "11:00"},
        {"id": 1, "store_code": "SS-18", "purchase_date": "2024/06/06", "purchase_time": "09:45"},
    ]
    ordered = sort_receipts_for_bulk_matching(receipts)
    assert ordered[0]["id"] == 1
    assert ordered[1]["id"] == 2

    used: set[str] = set()
    first = collect_link_skus_for_receipt(ordered[0], purchase_records, used, store_code="SS-18")
    used.update(first)
    second = collect_link_skus_for_receipt(ordered[1], purchase_records, used, store_code="SS-18")

    assert first == ["SKU-A", "SKU-B"]
    assert second == ["SKU-C"]


def test_manual_candidates_store_before_same_day():
    receipt = {
        "purchase_date": "2024/06/06",
        "purchase_time": "11:00",
        "store_code": "SS-18",
    }
    purchase_records = [
        {"SKU": "OTHER-1", "仕入れ日": "2024/06/06 10:00", "仕入先": "OF-10"},
        {"SKU": "SS-1", "仕入れ日": "2024/06/06 10:30", "仕入先": "SS-18"},
    ]
    entries = build_manual_candidate_entries(receipt, purchase_records, set())
    tiers = [e["tier"] for e in entries]
    skus = [e["sku"] for e in entries]
    assert skus.index("SS-1") < skus.index("OTHER-1")
    assert 1 in tiers and 2 in tiers


if __name__ == "__main__":
    test_bulk_matching_respects_time_and_used_skus()
    test_manual_candidates_store_before_same_day()
    print("ok")
