#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_break_even の pytest（Track A Phase 0 安全網）。"""

from __future__ import annotations

from desktop.services.purchase_break_even import (
    compute_break_even_for_record,
    compute_break_even_sale_price,
    implied_sale_deduction_at_planned_price,
    should_recompute_break_even,
)


def test_implied_uses_fee_components_when_present():
    implied = implied_sale_deduction_at_planned_price(
        5000,
        1000,
        3000,
        amazon_fee=500,
        shipping_price=200,
    )
    assert implied == 700


def test_implied_fallback_when_no_fee_info():
    """見込み利益が粗利と同じで手数料が無いとき、12% または 400円の大きい方"""
    implied = implied_sale_deduction_at_planned_price(5000, 1000, 4000)
    assert implied == max(5000 * 0.12, 400.0)


def test_compute_break_even_sale_price_with_fees():
    # implied=700, k=700/5000=0.14, BE = 1000 / 0.86
    be = compute_break_even_sale_price(
        1000,
        5000,
        3300,
        amazon_fee=500,
        shipping_price=200,
    )
    assert be is not None
    assert abs(be - (1000 / 0.86)) < 0.01


def test_compute_break_even_for_record():
    rec = {
        "仕入れ価格": 1000,
        "販売予定価格": 5000,
        "見込み利益": 3300,
        "プラットフォーム手数料": 500,
        "出荷費用": 200,
    }
    # shipping key in compute_break_even_for_record is 送料 / shipping-price, not 出荷費用
    # Use amazon-fee and shipping-price keys that the function reads
    rec2 = {
        "仕入れ価格": 1000,
        "販売予定価格": 5000,
        "見込み利益": 3300,
        "amazon-fee": 500,
        "shipping-price": 200,
    }
    be = compute_break_even_for_record(rec2)
    assert be is not None
    assert abs(be - (1000 / 0.86)) < 0.01


def test_should_recompute_when_stored_equals_purchase_and_no_fee_in_profit():
    """保存値≒仕入かつ粗利のみ（手数料未反映）→ 再計算 True"""
    assert should_recompute_break_even(1000, 1000, 5000, 4000) is True


def test_should_not_recompute_when_stored_differs_from_purchase():
    """保存値が仕入と大きく違う（akaji 相当）→ 尊重して再計算しない"""
    assert should_recompute_break_even(1700, 1000, 5000, 3300) is False


def test_should_recompute_when_stored_missing():
    assert should_recompute_break_even(None, 1000, 5000, 3000) is True
    assert should_recompute_break_even("", 1000, 5000, 3000) is True
