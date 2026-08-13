#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""販売DB upsert（未確定0円の上書き）の単体テスト。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _FakeSalesDb:
    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        self.rows = list(rows or [])
        self._next_id = max((int(r.get("id") or 0) for r in self.rows), default=0) + 1

    def list_all(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.rows]

    def insert(self, sale: Dict[str, Any]) -> int:
        row = dict(sale)
        row["id"] = self._next_id
        self._next_id += 1
        self.rows.append(row)
        return int(row["id"])

    def update(self, sale_id: int, sale: Dict[str, Any]) -> bool:
        for i, row in enumerate(self.rows):
            if int(row.get("id") or 0) == int(sale_id):
                merged = {**row, **sale, "id": sale_id}
                self.rows[i] = merged
                return True
        return False


def _make_widget(fake_db: _FakeSalesDb):
    from desktop.ui.product.widget import ProductWidget

    # ProductWidget の __init__ は重いので、必要メソッドだけ載せる
    class W:
        sales_db = fake_db
        _to_int_amount = staticmethod(ProductWidget._to_int_amount)
        _to_int_count = staticmethod(ProductWidget._to_int_count)
        _normalize_text = staticmethod(ProductWidget._normalize_text)
        _normalize_sale_date_key = staticmethod(ProductWidget._normalize_sale_date_key)
        _build_sale_dedupe_key = ProductWidget._build_sale_dedupe_key
        _upsert_sales_payloads = ProductWidget._upsert_sales_payloads

    return W()


def test_overwrite_zero_price_when_same_order_sku():
    db = _FakeSalesDb(
        [
            {
                "id": 1,
                "sku": "SKU-A",
                "sale_date": "2026-08-01",
                "sale_price": 0,
                "order_id": "503-111-222",
                "transaction_method": "Unshipped",
                "platform_fee": 0,
            }
        ]
    )
    w = _make_widget(db)
    result = w._upsert_sales_payloads(
        [
            {
                "sku": "SKU-A",
                "sale_date": "2026-08-01",
                "sale_price": 3980,
                "order_id": "503-111-222",
                "transaction_method": "Shipped",
                "sales_method": "FBA",
                "platform": "Amazon",
                "quantity": 1,
                "platform_fee": 0,
                "shipping_fee": 0,
                "other_fees": 0,
            }
        ]
    )
    assert result["updated"] == 1
    assert result["inserted"] == 0
    assert db.rows[0]["sale_price"] == 3980
    assert db.rows[0]["transaction_method"] == "Shipped"


def test_overwrite_zero_price_provisional_without_order_id():
    """注文IDなしの0円行に、注文ID付きの確定金額を上書きする。"""
    db = _FakeSalesDb(
        [
            {
                "id": 2,
                "sku": "SKU-B",
                "sale_date": "2026/08/02",  # 表記ゆれ
                "sale_price": 0,
                "order_id": "",
                "transaction_method": "",
            }
        ]
    )
    w = _make_widget(db)
    result = w._upsert_sales_payloads(
        [
            {
                "sku": "SKU-B",
                "sale_date": "2026-08-02",
                "sale_price": 2500,
                "order_id": "503-999-888",
                "transaction_method": "Unshipped",
                "sales_method": "FBA",
                "platform": "Amazon",
                "quantity": 1,
            }
        ]
    )
    assert result["updated"] == 1
    assert db.rows[0]["sale_price"] == 2500
    assert db.rows[0]["order_id"] == "503-999-888"


def test_do_not_overwrite_confirmed_price_as_duplicate():
    db = _FakeSalesDb(
        [
            {
                "id": 3,
                "sku": "SKU-C",
                "sale_date": "2026-08-03",
                "sale_price": 5000,
                "order_id": "503-aaa-bbb",
                "transaction_method": "Shipped",
                "platform_fee": 500,
            }
        ]
    )
    w = _make_widget(db)
    result = w._upsert_sales_payloads(
        [
            {
                "sku": "SKU-C",
                "sale_date": "2026-08-03",
                "sale_price": 5000,
                "order_id": "503-aaa-bbb",
                "transaction_method": "Shipped",
                "sales_method": "FBA",
                "platform": "Amazon",
                "quantity": 1,
                "platform_fee": 0,
            }
        ]
    )
    assert result["skipped_duplicate"] == 1
    assert db.rows[0]["sale_price"] == 5000
    assert db.rows[0]["platform_fee"] == 500
