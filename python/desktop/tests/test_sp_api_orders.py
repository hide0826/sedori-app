#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SP-API 注文→販売レコード変換の単体テスト。"""

from __future__ import annotations

from desktop.services.sp_api_orders import (
    SALE_COUNTABLE_TX_METHODS,
    extract_order_items_page,
    extract_orders_page,
    format_sale_date,
    order_item_to_sale_payload,
    sales_method_from_order,
    transaction_method_from_order,
)


def test_format_sale_date():
    # UTC → 日本時間（+9）で時刻まで残す
    assert format_sale_date("2024-03-15T10:00:00.000Z") == "2024-03-15 19:00:00"
    assert format_sale_date("2024-03-15T01:23:45+00:00") == "2024-03-15 10:23:45"
    assert format_sale_date("2024-03-15 20:17:04") == "2024-03-15 20:17:04"
    assert format_sale_date("2024/03/15") == "2024-03-15"
    assert format_sale_date("") == ""


def test_extract_orders_page():
    body = {
        "payload": {
            "Orders": [
                {"AmazonOrderId": "111-222", "OrderStatus": "Shipped"},
            ],
            "NextToken": "abc",
        }
    }
    orders, token = extract_orders_page(body)
    assert len(orders) == 1
    assert token == "abc"


def test_extract_order_items_page():
    body = {
        "payload": {
            "OrderItems": [
                {"SellerSKU": "SKU1", "QuantityOrdered": 1, "ItemPrice": {"Amount": "1000"}},
            ],
            "NextToken": "",
        }
    }
    items, token = extract_order_items_page(body)
    assert len(items) == 1
    assert token == ""


def test_sales_method_from_order():
    assert sales_method_from_order({"FulfillmentChannel": "AFN"}) == "FBA"
    assert sales_method_from_order({"FulfillmentChannel": "MFN"}) == "自己発送"


def test_transaction_method_countable():
    assert "shipped" in SALE_COUNTABLE_TX_METHODS
    assert "unshipped" in SALE_COUNTABLE_TX_METHODS
    assert transaction_method_from_order({"OrderStatus": "Unshipped"}) == "Unshipped"
    assert "pending" not in SALE_COUNTABLE_TX_METHODS


def test_order_item_to_sale_payload():
    order = {
        "AmazonOrderId": "503-1234567-1234567",
        "PurchaseDate": "2026-08-01T12:00:00Z",
        "OrderStatus": "Shipped",
        "FulfillmentChannel": "AFN",
    }
    item = {
        "SellerSKU": "20260801-TEST",
        "Title": "テスト商品",
        "QuantityOrdered": 2,
        "ItemPrice": {"CurrencyCode": "JPY", "Amount": "3000"},
    }
    payload = order_item_to_sale_payload(order, item)
    assert payload is not None
    assert payload["sku"] == "20260801-TEST"
    assert payload["sale_date"] == "2026-08-01 21:00:00"  # UTC 12:00 → JST 21:00
    assert payload["sale_price"] == 3000
    assert payload["quantity"] == 2
    assert payload["order_id"] == "503-1234567-1234567"
    assert payload["sales_method"] == "FBA"
    assert payload["transaction_method"] == "Shipped"
    assert payload["platform"] == "Amazon"


def test_order_item_requires_sku():
    order = {
        "AmazonOrderId": "1",
        "PurchaseDate": "2026-08-01T00:00:00Z",
        "OrderStatus": "Shipped",
    }
    assert order_item_to_sale_payload(order, {"QuantityOrdered": 1}) is None


def test_apply_purchase_fees_to_sale_computes_profit():
    from desktop.services.sp_api_orders import apply_purchase_fees_to_sale

    sale = {
        "sku": "SKU1",
        "sale_price": 5000,
        "quantity": 1,
        "platform_fee": 0,
        "shipping_fee": 0,
        "fba_fee": 0,
        "storage_fee": 0,
        "other_fees": 0,
    }
    purchase = {
        "プラットフォーム手数料": 500,
        "出荷費用": 300,
        "仕入れ価格": 2000,
    }
    out = apply_purchase_fees_to_sale(sale, purchase)
    assert out["platform_fee"] == 500
    assert out["shipping_fee"] == 300
    # 5000 - 500 - 300 - 2000 = 2200
    assert out["net_profit"] == 2200


def test_apply_purchase_fees_scales_by_quantity():
    from desktop.services.sp_api_orders import apply_purchase_fees_to_sale

    sale = {
        "sku": "SKU2",
        "sale_price": 10000,
        "quantity": 2,
        "platform_fee": 0,
        "shipping_fee": 0,
        "fba_fee": 0,
        "storage_fee": 0,
        "other_fees": 0,
    }
    purchase = {
        "プラットフォーム手数料": 400,
        "出荷費用": 200,
        "仕入れ価格": 1500,
    }
    out = apply_purchase_fees_to_sale(sale, purchase)
    assert out["platform_fee"] == 800
    assert out["shipping_fee"] == 400
    # 10000 - 800 - 400 - 3000 = 5800
    assert out["net_profit"] == 5800
