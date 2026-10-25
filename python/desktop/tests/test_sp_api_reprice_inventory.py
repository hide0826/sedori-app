#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sp_api_inventory / sp_api_reprice の単体テスト。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from desktop.services.sp_api_inventory import (
    humanize_listings_report_error,
    listings_rows_to_dataframe,
    merchant_listing_row_to_pricetar,
    parse_merchant_listings_text,
    pick_reusable_listings_report,
    write_pricetar_temp_csv,
)
from desktop.services import sp_api_inventory as inv
from desktop.services.sp_api_reprice import (
    collect_price_patch_targets,
    extract_product_type,
)


def test_merchant_listing_row_to_pricetar_maps_columns():
    row = {
        "seller-sku": "20250201-B000TEST-UM-1000-1",
        "asin1": "B000TEST01",
        "item-name": "テスト商品",
        "price": "1980",
        "quantity": "2",
        "item-condition": "11",
        "status": "Active",
    }
    mapped = merchant_listing_row_to_pricetar(row, purchase={"cost": 800})
    assert mapped is not None
    assert mapped["SKU"] == "20250201-B000TEST-UM-1000-1"
    assert mapped["ASIN"] == "B000TEST01"
    assert mapped["price"] == 1980
    assert mapped["number"] == 2
    assert mapped["cost"] == 800
    assert mapped["priceTrace"] == 0
    assert mapped["akaji"] == 0


def test_merchant_listing_row_japanese_headers():
    row = {
        "出品者SKU": "JP-SKU-1",
        "商品名": "日本語商品",
        "商品ID": "B00JPTEST1",
        "価格": "2500",
        "数量": "3",
        "ステータス": "アクティブ",
        "コンディション": "11",
    }
    mapped = merchant_listing_row_to_pricetar(row)
    assert mapped is not None
    assert mapped["SKU"] == "JP-SKU-1"
    assert mapped["ASIN"] == "B00JPTEST1"
    assert mapped["price"] == 2500
    assert mapped["number"] == 3
    assert mapped["title"] == "日本語商品"


def test_inactive_listing_skipped():
    row = {
        "seller-sku": "SKU1",
        "asin1": "B0001",
        "price": "1000",
        "status": "Inactive",
    }
    assert merchant_listing_row_to_pricetar(row) is None


def test_listings_rows_to_dataframe_dedupes_sku(monkeypatch):
    monkeypatch.setattr(inv, "_load_purchase_cost_map", lambda skus: {})
    rows = [
        {"seller-sku": "A", "asin1": "B1", "price": "100", "quantity": "1", "status": "Active"},
        {"seller-sku": "A", "asin1": "B1", "price": "200", "quantity": "1", "status": "Active"},
        {"seller-sku": "B", "asin1": "B2", "price": "300", "quantity": "0", "status": "Active"},
    ]
    df = listings_rows_to_dataframe(rows)
    assert len(df) == 2
    assert list(df["SKU"]) == ["A", "B"]
    assert int(df.iloc[0]["price"]) == 100
    assert "priceTrace" in df.columns
    assert int(df.iloc[0]["priceTrace"]) == 0


def test_parse_merchant_listings_text_skips_preamble():
    text = (
        "All Listings Report\n"
        "Generated for seller\n"
        "item-name\tseller-sku\tprice\tquantity\tasin1\tstatus\n"
        "Widget\tSKU-A\t1200\t1\tB0001\tActive\n"
        "Gadget\tSKU-B\t3400\t2\tB0002\tActive\n"
    )
    rows = parse_merchant_listings_text(text)
    assert len(rows) == 2
    assert rows[0]["seller-sku"] == "SKU-A"
    df = listings_rows_to_dataframe(rows)
    assert len(df) == 2
    assert int(df.iloc[0]["price"]) == 1200


def test_parse_merchant_listings_text_japanese_csv():
    text = (
        "商品名,出品者SKU,価格,数量,商品ID,ステータス\n"
        "テスト,SKU-JP,999,1,B00X,アクティブ\n"
    )
    rows = parse_merchant_listings_text(text)
    assert len(rows) == 1
    mapped = merchant_listing_row_to_pricetar(rows[0])
    assert mapped is not None
    assert mapped["SKU"] == "SKU-JP"
    assert mapped["price"] == 999


def test_positional_fallback_when_headers_garbled(monkeypatch):
    """列名が壊れていても公式列順でSKUを拾える。"""
    monkeypatch.setattr(inv, "_load_purchase_cost_map", lambda skus: {})
    # 公式順: 0=name ... 3=sku 4=price 5=qty ... 16=asin1 ... 22=product-id ... 28=status
    values = [""] * 30
    values[0] = "商品A"
    values[3] = "POS-SKU-1"
    values[4] = "1500"
    values[5] = "1"
    values[16] = "B00POS1"
    values[28] = "Active"
    # 意図的に意味のない列名
    row = {f"col{i}": values[i] for i in range(30)}
    df = listings_rows_to_dataframe([row])
    assert len(df) == 1
    assert df.iloc[0]["SKU"] == "POS-SKU-1"
    assert int(df.iloc[0]["price"]) == 1500


def test_write_pricetar_temp_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(inv.tempfile, "gettempdir", lambda: str(tmp_path))
    df = pd.DataFrame(
        [
            {
                "SKU": "S1",
                "ASIN": "B1",
                "title": "t",
                "number": 1,
                "price": 1000,
                "cost": 100,
                "akaji": 0,
                "takane": 0,
                "condition": "11",
                "conditionNote": "",
                "priceTrace": 0,
                "leadtime": "",
                "amazon-fee": 0,
                "shipping-price": 0,
                "profit": 0,
                "add-delete": "",
            }
        ]
    )
    path = write_pricetar_temp_csv(df, prefix="test_")
    assert Path(path).exists()
    loaded = pd.read_csv(path)
    assert "SKU" in loaded.columns
    assert loaded.iloc[0]["SKU"] == "S1"


def test_collect_price_patch_targets_only_changed():
    items = [
        {"sku": "A", "price": 1000, "new_price": 1000},
        {"sku": "B", "price": 1000, "new_price": 990},
        {"sku": "C", "price": 2000, "new_price": 0},
        {"sku": "B", "price": 1000, "new_price": 980},
    ]
    targets = collect_price_patch_targets(items)
    assert len(targets) == 1
    assert targets[0]["sku"] == "B"
    assert targets[0]["new_price"] == 990


def test_extract_product_type():
    assert extract_product_type({"summaries": [{"productType": "LUGGAGE"}]}) == "LUGGAGE"
    assert extract_product_type({}) == "PRODUCT"


def test_pick_reusable_listings_report_prefers_fresh_done():
    now = 1_700_000_000.0
    reports = [
        {
            "reportId": "old-done",
            "processingStatus": "DONE",
            "reportDocumentId": "doc-old",
            "createdTime": "2023-11-14T22:00:00Z",
        },
        {
            "reportId": "fresh-done",
            "processingStatus": "DONE",
            "reportDocumentId": "doc-fresh",
            "createdTime": "2023-11-14T22:10:00Z",
        },
        {
            "reportId": "running",
            "processingStatus": "IN_PROGRESS",
            "createdTime": "2023-11-14T22:12:00Z",
        },
    ]
    done, inflight = pick_reusable_listings_report(reports, now_epoch=now)
    assert done is not None
    assert done["reportId"] == "fresh-done"
    assert inflight is not None
    assert inflight["reportId"] == "running"


def test_pick_reusable_listings_report_skips_stale_done():
    now = 1_700_000_000.0
    reports = [
        {
            "reportId": "stale",
            "processingStatus": "DONE",
            "reportDocumentId": "doc-stale",
            "createdTime": "2023-11-14T18:00:00Z",
        }
    ]
    done, inflight = pick_reusable_listings_report(reports, now_epoch=now, max_age_sec=90 * 60)
    assert done is None
    assert inflight is None


def test_humanize_listings_report_error_secret_expired():
    msg = humanize_listings_report_error(
        RuntimeError("HTTP 403 body={'errors': [{'message': 'The LWA secret token you provided has expired.'}]}")
    )
    assert "クライアントシークレット" in msg
    assert "SP_API_CLIENT_SECRET" in msg
