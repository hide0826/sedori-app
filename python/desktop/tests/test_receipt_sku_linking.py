#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from datetime import date, datetime

from desktop.services.receipt_sku_linking import (
    build_manual_candidate_entries,
    collect_link_skus_for_receipt,
    get_record_sku,
    is_purchase_before_receipt,
    is_same_day,
    normalize_store_code,
    parse_date_only,
    parse_purchase_record_datetime,
    parse_receipt_datetime,
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


def test_normalize_store_code_strips_after_space():
    assert normalize_store_code("SS-18 店舗名") == "SS-18"
    assert normalize_store_code("  AB-1  ") == "AB-1"
    assert normalize_store_code("") == ""
    assert normalize_store_code(None) == ""


def test_parse_date_only_formats():
    assert parse_date_only("2024/06/06") == date(2024, 6, 6)
    assert parse_date_only("2024-06-06 09:30:00") == date(2024, 6, 6)
    assert parse_date_only("2024-06-06T09:30:00") == date(2024, 6, 6)
    assert parse_date_only("") is None
    assert parse_date_only("not-a-date") is None


def test_get_record_sku_filters_invalid():
    assert get_record_sku({"SKU": "ABC-1"}) == "ABC-1"
    assert get_record_sku({"sku": "xyz-2"}) == "xyz-2"
    assert get_record_sku({"SKU": "未実装"}) == ""
    assert get_record_sku({"SKU": "nan"}) == ""
    assert get_record_sku({"SKU": "None"}) == ""
    assert get_record_sku({}) == ""


def test_parse_receipt_datetime_combines_date_and_time():
    receipt = {"purchase_date": "2024/06/06", "purchase_time": "14:30"}
    assert parse_receipt_datetime(receipt) == datetime(2024, 6, 6, 14, 30)


def test_parse_receipt_datetime_date_only_is_end_of_day():
    receipt = {"purchase_date": "2024/06/06", "purchase_time": ""}
    assert parse_receipt_datetime(receipt) == datetime(2024, 6, 6, 23, 59, 59)


def test_parse_purchase_record_datetime():
    record = {"仕入れ日": "2024/06/06 09:15", "仕入先": "SS-18"}
    assert parse_purchase_record_datetime(record) == datetime(2024, 6, 6, 9, 15)


def test_is_same_day_and_purchase_before_receipt():
    receipt = {"purchase_date": "2024/06/06", "purchase_time": "11:00"}
    same = {"仕入れ日": "2024/06/06 10:00", "仕入先": "SS-18"}
    other_day = {"仕入れ日": "2024/06/07 10:00", "仕入先": "SS-18"}
    after = {"仕入れ日": "2024/06/06 12:00", "仕入先": "SS-18"}

    assert is_same_day(same, receipt) is True
    assert is_same_day(other_day, receipt) is False
    assert is_purchase_before_receipt(same, receipt) is True
    assert is_purchase_before_receipt(after, receipt) is False


def test_collect_link_skus_prefers_image_file_name_match():
    receipt = {
        "purchase_date": "2024/06/06",
        "purchase_time": "11:00",
        "store_code": "SS-18",
        "file_path": r"D:\data\receipts\IMG_001.jpg",
    }
    purchase_records = [
        {
            "SKU": "BY-STORE",
            "仕入れ日": "2024/06/06 09:00",
            "仕入先": "SS-18",
        },
        {
            "SKU": "BY-IMAGE",
            "仕入れ日": "2024/06/07 09:00",
            "仕入先": "OTHER",
            "レシートID": "IMG_001",
        },
    ]
    linked = collect_link_skus_for_receipt(receipt, purchase_records, set())
    assert linked == ["BY-IMAGE"]
