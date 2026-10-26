#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全額返金のときだけ仕入ステータスを返金にする。"""

from __future__ import annotations

from desktop.services.sp_api_sales_sync import (
    sku_sales_fully_refunded,
    sync_refunded_purchase_status,
)


def test_partial_refund_does_not_count_as_full():
    sales = [
        {"transaction_method": "shipped", "sale_price": 3000, "refund_total": 3000, "quantity": 1},
        {"transaction_method": "shipped", "sale_price": 2000, "refund_total": 0, "quantity": 1},
    ]
    assert sku_sales_fully_refunded(sales) is False


def test_all_lines_refunded():
    sales = [
        {"transaction_method": "Shipped", "sale_price": 3000, "refund_total": 3000, "quantity": 1},
        {"transaction_method": "shipped", "sale_price": 1500, "refund_total": 1500, "quantity": 1},
    ]
    assert sku_sales_fully_refunded(sales) is True


class _Sales:
    def __init__(self, rows):
        self.rows = rows

    def list_all(self):
        return list(self.rows)


class _Purchases:
    def __init__(self):
        self.rows = {
            "FULL": {"sku": "FULL", "status": "sold"},
            "PART": {"sku": "PART", "status": "sold"},
            "KEEP": {"sku": "KEEP", "status": "storage"},
        }
        self.written = []

    def get_by_sku(self, sku):
        row = self.rows.get(sku)
        return dict(row) if row else None

    def upsert(self, payload):
        self.written.append(dict(payload))
        return 1


def test_only_fully_refunded_sku_changes_status():
    sales = _Sales(
        [
            {"sku": "FULL", "transaction_method": "shipped", "sale_price": 4000, "refund_total": 4000},
            {"sku": "PART", "transaction_method": "shipped", "sale_price": 4000, "refund_total": 1000},
            {"sku": "KEEP", "transaction_method": "shipped", "sale_price": 4000, "refund_total": 4000},
        ]
    )
    purchases = _Purchases()
    summary = sync_refunded_purchase_status(sales, purchases)
    assert summary["updated_refunded"] == 1
    assert purchases.written[0]["sku"] == "FULL"
    assert purchases.written[0]["status"] == "refunded"
