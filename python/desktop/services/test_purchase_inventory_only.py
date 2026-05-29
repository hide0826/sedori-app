#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_inventory_only の単体テスト（pytest 不要・直接実行可）"""

import pandas as pd

from purchase_inventory_only import (
    build_inventory_only_display_record,
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
    df = pd.DataFrame([{
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
    }])
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


def test_condition_labels():
    from condition_labels import (
        backfill_condition_label_in_record,
        normalize_condition_display,
    )

    assert normalize_condition_display("2") == "中古(非常に良い)"
    assert normalize_condition_display("11") == "新品(新品)"
    assert normalize_condition_display("1") == "中古(ほぼ新品)"
    assert normalize_condition_display("中古(良い)") == "中古(良い)"

    rec = {"コンディション": "3"}
    backfill_condition_label_in_record(rec)
    assert rec["コンディション"] == "中古(良い)"
    assert rec["condition_code"] == 3


def test_extract_rows_includes_asin_empty_existing():
    df = pd.DataFrame([{
        "SKU": "20260103-BO-06-020",
        "ASIN": "B0B7L1GS",
        "title": "テスト商品",
        "number": "1",
        "price": "7000",
        "cost": "700",
        "amazon-fee": "1170",
        "profit": "3855",
        "akaji": "1870",
    }])

    class FakeDb:
        def get_by_sku(self, sku):
            return {"sku": sku, "status": "inventory_only"}

    display = [{"SKU": "20260103-BO-06-020", "ASIN": "", "商品名": ""}]
    from purchase_inventory_only import extract_rows_not_in_purchase_db

    rows = extract_rows_not_in_purchase_db(df, FakeDb(), display_records=display)
    assert len(rows) == 1
    assert rows[0]["overwrite"] is True

    display_ok = [{"SKU": "20260103-BO-06-020", "ASIN": "B0B7L1GS", "商品名": "済"}]
    rows_skip = extract_rows_not_in_purchase_db(df, FakeDb(), display_records=display_ok)
    assert len(rows_skip) == 0


def test_backfill_purchase_date_from_sku():
    from purchase_inventory_only import backfill_purchase_date_from_sku

    rec = {"SKU": "251026-2-040", "仕入れ日": ""}
    backfill_purchase_date_from_sku(rec)
    assert rec["仕入れ日"] == "2025/10/26"
    assert rec["purchase_date"] == "2025/10/26"

    rec2 = {"SKU": "251026-2-040", "仕入れ日": "2025/09/01"}
    backfill_purchase_date_from_sku(rec2)
    assert rec2["仕入れ日"] == "2025/09/01"


if __name__ == "__main__":
    test_parse_purchase_date_from_sku()
    test_row_dict_from_inventory_csv()
    test_build_inventory_only_display_record()
    test_extract_rows_includes_asin_empty_existing()
    test_backfill_purchase_date_from_sku()
    test_condition_labels()
    print("OK: test_purchase_inventory_only")
