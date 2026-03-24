#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DBの「損益分岐点」（販売価格ベースの目安）を推定する。

レシート連携等で「仕入れ価格 + その他費用」だけとすると、手数料・送料相当が無い扱いになり
損益分岐点が仕入れ価格と同じ値に潰れる。ここでは販売予定価格・見込み利益から
「販売価格に対する控除の割合」を推定し、利益ゼロとなる販売価格を求める。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def implied_sale_deduction_at_planned_price(
    planned_sale: float,
    purchase: float,
    expected_profit: float,
    other_cost: float = 0.0,
    *,
    amazon_fee: Optional[float] = None,
    shipping_price: Optional[float] = None,
) -> float:
    """
    販売予定価格における「売上から控除される額」（手数料+送料等の合算イメージ）。

    amazon_fee / shipping_price がレコードにあれば優先。なければ
    planned - purchase - other - profit から逆算。
    異常値のときはフォールバック。
    """
    planned_sale = float(planned_sale)
    purchase = float(purchase)
    other_cost = float(other_cost or 0)
    expected_profit = float(expected_profit or 0)

    fee = 0.0
    ship = 0.0
    if amazon_fee is not None:
        fee = max(0.0, float(amazon_fee))
    if shipping_price is not None:
        ship = max(0.0, float(shipping_price))

    if fee > 0 or ship > 0:
        implied = fee + ship
    else:
        implied = planned_sale - purchase - other_cost - expected_profit

    # 見込み利益が「販売予定−仕入」だけ等で手数料が反映されていない → implied≦0
    if implied < 1.0:
        implied = max(planned_sale * 0.12, 400.0)

    return implied


def compute_break_even_sale_price(
    purchase: float,
    planned_sale: float,
    expected_profit: float,
    other_cost: float = 0.0,
    *,
    amazon_fee: Optional[float] = None,
    shipping_price: Optional[float] = None,
) -> Optional[float]:
    """
    利益ゼロとなる販売価格の目安（控除が販売価格に比例すると仮定）。

    S * (1 - k) = purchase + other_cost、 k = implied / planned_sale
    """
    if planned_sale <= 0:
        return None
    purchase = float(purchase)
    other_cost = float(other_cost or 0)

    implied = implied_sale_deduction_at_planned_price(
        planned_sale,
        purchase,
        expected_profit,
        other_cost,
        amazon_fee=amazon_fee,
        shipping_price=shipping_price,
    )
    k = implied / float(planned_sale)
    if k >= 1.0 or k < 0:
        return purchase + other_cost
    denom = 1.0 - k
    if denom <= 1e-9:
        return purchase + other_cost
    return (purchase + other_cost) / denom


def compute_break_even_for_record(record: Dict[str, Any]) -> Optional[float]:
    """仕入DBレコード辞書から数値を取り出して損益分岐点を計算。"""
    purchase = None
    for key in ("仕入れ価格", "仕入価格", "purchase_price", "cost"):
        if key in record and record[key] not in (None, ""):
            purchase = _to_float(record[key])
            break
    if purchase is None:
        return None

    planned = None
    for key in ("販売予定価格", "planned_price", "price"):
        if key in record and record[key] not in (None, ""):
            planned = _to_float(record[key])
            break
    if planned is None or planned <= 0:
        return None

    profit = 0.0
    for key in ("見込み利益", "expected_profit", "profit"):
        if key in record and record[key] not in (None, ""):
            profit = _to_float(record[key])
            break

    other_cost = _to_float(record.get("その他費用") or record.get("other_cost"))

    amz = None
    for key in ("amazon-fee", "amazon_fee", "Amazon手数料"):
        if key in record and record[key] not in (None, ""):
            amz = _to_float(record[key])
            break

    ship = None
    for key in ("shipping-price", "shipping_price", "送料"):
        if key in record and record[key] not in (None, ""):
            ship = _to_float(record[key])
            break

    return compute_break_even_sale_price(
        purchase,
        planned,
        profit,
        other_cost,
        amazon_fee=amz,
        shipping_price=ship,
    )


def should_recompute_break_even(
    stored: Any,
    purchase: float,
    planned_sale: float,
    expected_profit: float,
    other_cost: float = 0.0,
    *,
    epsilon: float = 0.51,
) -> bool:
    """
    再計算が必要か。

    - 欠損・不正・0 は再計算
    - 保存値が仕入れと大きく違う（価格改定CSVの akaji 等）は尊重して再計算しない
    - 保存値≒仕入れかつ「見込み利益が手数料を含まない粗利」のときだけ再計算
      （planned - purchase - other - profit がほぼ 0）
    """
    if planned_sale <= 0:
        return False
    try:
        pur = float(purchase)
    except (TypeError, ValueError):
        return True
    if stored is None or stored == "":
        return True
    try:
        s = float(str(stored).replace(",", "").strip())
    except (ValueError, TypeError):
        return True
    if s <= 0:
        return True
    if abs(s - pur) > epsilon:
        return False
    oc = float(other_cost or 0)
    exp = float(expected_profit or 0)
    implied_deduction = float(planned_sale) - pur - oc - exp
    return implied_deduction < 1.0
