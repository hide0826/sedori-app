#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入レコードの販売チャネル別手数料・利益再計算ヘルパー。"""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from services.purchase_cost_calc import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        cell_has_numeric_value,
        fee_storage_value,
        migrate_record_keys,
        resolve_total_cost_for_fee_calc,
        recalculate_profit_fields,
        to_float,
    )
except ImportError:
    from desktop.services.purchase_cost_calc import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        cell_has_numeric_value,
        fee_storage_value,
        migrate_record_keys,
        resolve_total_cost_for_fee_calc,
        recalculate_profit_fields,
        to_float,
    )


def is_amazon_sales_channel(channel: str) -> bool:
    return str(channel or "").strip().lower() == "amazon"


def flea_fee_rate_percent_for_channel(channel: str, store_db: Any) -> Optional[float]:
    """
    設定タブのフリマ設定（flea_markets.fee_rate）を販売チャネル名で参照する。
    Amazon のときは None（FBAシミュ等の手入力を優先）。
    """
    if is_amazon_sales_channel(channel) or store_db is None:
        return None
    name = str(channel or "").strip()
    if not name:
        return None
    market = None
    if hasattr(store_db, "get_flea_market_by_platform_name"):
        market = store_db.get_flea_market_by_platform_name(name)
    if not market and hasattr(store_db, "list_flea_markets"):
        for m in store_db.list_flea_markets(active_only=True):
            if str(m.get("platform_name") or "").strip() == name:
                market = m
                break
    if not market:
        return None
    raw = market.get("fee_rate")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return None
    if rate < 0:
        return None
    return rate


def platform_fee_from_sale_price(planned_price: float, fee_rate_percent: float) -> int:
    planned_price = max(0.0, float(planned_price or 0))
    rate = max(0.0, float(fee_rate_percent or 0))
    return int(round(planned_price * rate / 100.0))


def apply_fee_values_to_record(
    record: Dict[str, Any],
    *,
    purchase_price: float,
    planned_price: float,
    platform_fee: float,
    shipping_cost: float,
) -> Dict[str, Any]:
    """手数料内訳から費用合計・見込み利益・想定利益率/ROI を record に書き込む。"""
    migrate_record_keys(record)
    total = resolve_total_cost_for_fee_calc(
        record,
        platform_fee=platform_fee,
        shipping_cost=shipping_cost,
        purchase_price=purchase_price,
        planned_price=planned_price,
    )
    fields = recalculate_profit_fields(
        purchase_price,
        planned_price,
        platform_fee,
        shipping_cost,
        total,
        prefer_stored_profit=False,
        prefer_stored_break_even=False,
    )
    record[COL_PLATFORM_FEE] = fee_storage_value(platform_fee)
    record[COL_SHIPPING] = fee_storage_value(shipping_cost)
    record[COL_TOTAL_COST] = fee_storage_value(fields[COL_TOTAL_COST])
    record["見込み利益"] = int(fields["見込み利益"])
    record["expected_profit"] = record["見込み利益"]
    record["損益分岐点"] = int(fields["損益分岐点"])
    record["想定利益率"] = fields["想定利益率"]
    record["想定ROI"] = fields["想定ROI"]
    record["expected_margin"] = fields["想定利益率"]
    record["expected_roi"] = fields["想定ROI"]
    return fields
