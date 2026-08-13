#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""返品・返金パーサの単体テスト。"""

from __future__ import annotations

from desktop.services.sp_api_refunds import (
    apply_refund_to_sale,
    estimate_refund_amount,
    fba_return_row_to_refund,
    flat_return_row_to_refund,
    merge_refund_records,
    parse_finance_refund_events,
    parse_tsv_text,
)


def test_parse_tsv_text_fba_header():
    text = (
        "return-date\torder-id\tsku\tquantity\treason\n"
        "2026-08-01T00:00:00+00:00\t503-111-222\tSKU-A\t1\tUNWANTED\n"
    )
    rows = parse_tsv_text(text)
    assert len(rows) == 1
    rec = fba_return_row_to_refund(rows[0])
    assert rec is not None
    assert rec["order_id"] == "503-111-222"
    assert rec["sku"] == "SKU-A"
    assert rec["return_quantity"] == 1
    assert rec["refund_amount"] is None


def test_flat_return_with_refunded_amount():
    row = {
        "Order ID": "503-999-888",
        "Merchant SKU": "SKU-B",
        "Return quantity": "1",
        "Refunded Amount": "3,980",
        "Return request status": "Approved",
        "Return Reason": "Damaged",
    }
    rec = flat_return_row_to_refund(row)
    assert rec is not None
    assert rec["refund_amount"] == 3980


def test_parse_finance_refund_events():
    body = {
        "payload": {
            "FinancialEvents": {
                "RefundEventList": [
                    {
                        "AmazonOrderId": "503-1-2",
                        "PostedDate": "2026-08-01T00:00:00Z",
                        "ShipmentItemAdjustmentList": [
                            {
                                "SellerSKU": "SKU-C",
                                "QuantityShipped": 1,
                                "ItemChargeAdjustmentList": [
                                    {
                                        "ChargeType": "Principal",
                                        "ChargeAmount": {"CurrencyAmount": "-2500"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }
    }
    rows = parse_finance_refund_events(body)
    assert len(rows) == 1
    assert rows[0]["sku"] == "SKU-C"
    assert rows[0]["refund_amount"] == 2500


def test_merge_and_estimate_and_apply():
    merged = merge_refund_records(
        [
            {"order_id": "1", "sku": "A", "return_quantity": 1, "refund_amount": None, "source": "fba"},
            {"order_id": "1", "sku": "A", "return_quantity": 1, "refund_amount": 1000, "source": "flat"},
        ]
    )
    assert len(merged) == 1
    assert merged[0]["return_quantity"] == 2
    assert merged[0]["refund_amount"] == 1000

    sale = {
        "sale_price": 5000,
        "quantity": 1,
        "platform_fee": 500,
        "shipping_fee": 300,
        "fba_fee": 0,
        "storage_fee": 0,
        "other_fees": 0,
        "refund_total": 0,
        "net_profit": 2200,  # 5000-500-300-2000
    }
    assert estimate_refund_amount(sale, {"return_quantity": 1}) == 5000
    out = apply_refund_to_sale(sale, {"return_quantity": 1, "refund_amount": 5000})
    assert out["refund_total"] == 5000
    assert out["net_profit"] == -2800  # 2200 - 5000
