#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_inventory_only 純関数の pytest（Track A Phase 0 安全網）。"""

from __future__ import annotations

import pandas as pd

from desktop.services.purchase_inventory_only import (
    backfill_purchase_date_from_sku,
    build_inventory_only_display_record,
    build_inventory_only_upsert_payload,
    extract_rows_not_in_purchase_db,
    find_sku_column,
    normalize_sku_from_cell,
    normalize_status_code,
    parse_purchase_date_from_sku,
    row_dict_from_inventory_csv,
)


def test_parse_purchase_date_from_sku():
    assert parse_purchase_date_from_sku("20251220-used1-014") == "2025/12/20"
    assert parse_purchase_date_from_sku("251026-2-040") == "2025/10/26"
    assert parse_purchase_date_from_sku("251018-3-033-Q4") == "2025/10/18"
    assert parse_purchase_date_from_sku("hmk-20251115-used2-025") == "2025/11/15"
    assert parse_purchase_date_from_sku("invalid") == ""


def test_row_dict_from_inventory_csv():
    df = pd.DataFrame(
        [
            {
                "SKU": "20260103-BO-06-020",
                "ASIN": "B0B7L1GS",
                "title": "テスト商品",
                "number": "2",
                "price": "7000",
                "cost": "700",
                "akaji": "1870",
                "amazon-fee": "1170",
                "profit": "3855",
                "condition": "3",
            }
        ]
    )
    row = row_dict_from_inventory_csv(df, 0)
    assert row["仕入れ日"] == "2026/01/03"
    assert row["ASIN"] == "B0B7L1GS"
    assert row["商品名"] == "テスト商品"
    assert row["number"] == "2"
    assert row["cost"] == "700"
    assert row["price"] == "7000"
    assert row["profit"] == "3855"
    assert row["amazon-fee"] == "1170"
    assert row["akaji"] == "1870"


def test_build_inventory_only_display_record():
    row = {
        "SKU": "20251220-used1-014",
        "ASIN": "B07X1VC7",
        "title": "サンプル",
        "number": "1",
        "cost": "700",
        "price": "7000",
        "profit": "3855",
        "amazon-fee": "1170",
        "akaji": "1870",
        "condition": "2",
    }
    display = build_inventory_only_display_record(row)
    assert display["仕入れ日"] == "2025/12/20"
    assert display["仕入れ個数"] == 1
    assert display["仕入れ価格"] == 700
    assert display["販売予定価格"] == 7000
    assert display["見込み利益"] == 3855
    assert display["費用合計"] == 1170
    assert display["損益分岐点"] == 1870
    assert display["想定利益率"] > 0
    assert display["想定ROI"] > 0
    assert display["ステータス"] == "inventory_only"
    assert display["コンディション"] == "中古(非常に良い)"


def test_extract_rows_includes_asin_empty_existing():
    df = pd.DataFrame(
        [
            {
                "SKU": "20260103-BO-06-020",
                "ASIN": "B0B7L1GS",
                "title": "テスト商品",
                "number": "1",
                "price": "7000",
                "cost": "700",
                "amazon-fee": "1170",
                "profit": "3855",
                "akaji": "1870",
            }
        ]
    )

    class FakeDb:
        def get_by_sku(self, sku):
            return {"sku": sku, "status": "inventory_only"}

    display = [{"SKU": "20260103-BO-06-020", "ASIN": "", "商品名": ""}]
    rows = extract_rows_not_in_purchase_db(df, FakeDb(), display_records=display)
    assert len(rows) == 1
    assert rows[0]["overwrite"] is True

    display_ok = [{"SKU": "20260103-BO-06-020", "ASIN": "B0B7L1GS", "商品名": "済"}]
    rows_skip = extract_rows_not_in_purchase_db(df, FakeDb(), display_records=display_ok)
    assert len(rows_skip) == 0


def test_backfill_purchase_date_from_sku():
    rec = {"SKU": "251026-2-040", "仕入れ日": ""}
    backfill_purchase_date_from_sku(rec)
    assert rec["仕入れ日"] == "2025/10/26"
    assert rec["purchase_date"] == "2025/10/26"

    rec2 = {"SKU": "251026-2-040", "仕入れ日": "2025/09/01"}
    backfill_purchase_date_from_sku(rec2)
    assert rec2["仕入れ日"] == "2025/09/01"


def test_normalize_sku_from_cell():
    assert normalize_sku_from_cell('="20251220-used1-014"') == "20251220-used1-014"
    assert normalize_sku_from_cell("20251220-used1-014") == "20251220-used1-014"
    assert normalize_sku_from_cell(None) == ""
    assert normalize_sku_from_cell("nan") == ""
    assert normalize_sku_from_cell("  abc  ") == "abc"


def test_find_sku_column():
    df = pd.DataFrame([{"seller-sku": "a", "ASIN": "B0"}])
    assert find_sku_column(df) == "seller-sku"
    df2 = pd.DataFrame([{"SKU": "a"}])
    assert find_sku_column(df2) == "SKU"
    assert find_sku_column(pd.DataFrame([{"ASIN": "B0"}])) is None
    assert find_sku_column(pd.DataFrame()) is None


def test_normalize_status_code():
    assert normalize_status_code("在庫専用") == "inventory_only"
    assert normalize_status_code("出品可能") == "ready"
    assert normalize_status_code("selling") == "selling"
    assert normalize_status_code("") == "ready"
    assert normalize_status_code(None) == "ready"


def test_build_inventory_only_upsert_payload():
    payload = build_inventory_only_upsert_payload(
        {
            "SKU": "20251220-used1-014",
            "仕入れ価格": 700,
            "仕入れ個数": 1,
            "想定利益率": 55.0,
            "想定ROI": 500.0,
        }
    )
    assert payload["sku"] == "20251220-used1-014"
    assert payload["status"] == "inventory_only"
    assert payload["purchase_date"] == "2025/12/20"
    assert payload["purchase_price"] == 700
    assert payload["quantity"] == 1
    assert payload["repricing_enabled"] == 1
    assert payload["ladder_enabled"] == 0
    assert payload["expected_margin"] == 55.0
    assert payload["expected_roi"] == 500.0

    try:
        build_inventory_only_upsert_payload({})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "sku" in str(e).lower()
