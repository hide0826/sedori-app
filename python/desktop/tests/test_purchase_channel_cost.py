#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_channel_cost の pytest（Track A Phase 0 安全網）。"""

from __future__ import annotations

from desktop.services.purchase_channel_cost import (
    apply_fee_values_to_record,
    is_amazon_sales_channel,
    platform_fee_from_sale_price,
)
from desktop.services.purchase_cost_calc import COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST


def test_is_amazon_sales_channel():
    assert is_amazon_sales_channel("Amazon") is True
    assert is_amazon_sales_channel("amazon") is True
    assert is_amazon_sales_channel("メルカリ") is False
    assert is_amazon_sales_channel("") is False


def test_platform_fee_from_sale_price():
    assert platform_fee_from_sale_price(10000, 10.0) == 1000
    assert platform_fee_from_sale_price(3333, 10.0) == 333
    assert platform_fee_from_sale_price(0, 10.0) == 0
    assert platform_fee_from_sale_price(1000, 0) == 0


def test_apply_fee_values_to_record_aligns_totals():
    record = {
        "仕入れ価格": 1000,
        "販売予定価格": 5000,
        "見込み利益": 0,
    }
    fields = apply_fee_values_to_record(
        record,
        purchase_price=1000,
        planned_price=5000,
        platform_fee=500,
        shipping_cost=200,
    )
    assert record[COL_PLATFORM_FEE] == 500
    assert record[COL_SHIPPING] == 200
    assert record[COL_TOTAL_COST] == 700
    assert record["損益分岐点"] == 1700
    assert record["見込み利益"] == 3300
    assert fields[COL_TOTAL_COST] == 700
    assert fields["見込み利益"] == 3300
