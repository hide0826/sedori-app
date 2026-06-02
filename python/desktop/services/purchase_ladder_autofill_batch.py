#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DB一括: 月別運用の自動設定（TP未入力・月別OFFの行）。

priceTrace / FBA状態合わせ / 等間隔値下げ（最終0%）/ akaji2% / takane1%
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    from desktop.utils.purchase_elapsed_days import calc_elapsed_days_for_purchase_record
    from desktop.utils.purchase_repricing_summary import (
        is_ladder_mode,
        is_repricing_enabled,
    )
    from desktop.utils.repricer_ladder_table import (
        build_ladder_rules_with_standard_trace,
        ladder_rules_to_json,
    )
except ImportError:
    from utils.purchase_elapsed_days import calc_elapsed_days_for_purchase_record  # type: ignore
    from utils.purchase_repricing_summary import (  # type: ignore
        is_ladder_mode,
        is_repricing_enabled,
    )
    from utils.repricer_ladder_table import (  # type: ignore
        build_ladder_rules_with_standard_trace,
        ladder_rules_to_json,
    )


def _parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def record_sale_and_base_profit(record: Dict[str, Any]) -> Tuple[float, float]:
    sale = _parse_number(record.get("販売予定価格") or record.get("expected_price"))
    profit = _parse_number(record.get("見込み利益") or record.get("expected_profit"))
    return sale, profit


def is_tp_all_empty(record: Dict[str, Any]) -> bool:
    for key in ("TP0", "tp0", "TP1", "tp1", "TP2", "tp2", "TP3", "tp3"):
        raw = record.get(key)
        if raw is None:
            continue
        text = str(raw).strip().replace(",", "")
        if not text:
            continue
        try:
            if float(text) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def is_eligible_for_monthly_auto(record: Dict[str, Any]) -> bool:
    """TP未入力かつ月別OFF（価格改定ON・販売予定>0）。"""
    if is_ladder_mode(record):
        return False
    if not is_tp_all_empty(record):
        return False
    if not is_repricing_enabled(record):
        return False
    sale, _profit = record_sale_and_base_profit(record)
    return sale > 0


def apply_monthly_auto_ladder_to_record(
    record: Dict[str, Any],
    *,
    final_margin_percent: float = 0.0,
) -> Tuple[bool, str]:
    """
    レコードに月別運用ルールを設定する。成功時 True。
    """
    if not is_eligible_for_monthly_auto(record):
        return False, "対象外"

    sale, base_profit = record_sale_and_base_profit(record)
    elapsed = calc_elapsed_days_for_purchase_record(record)

    rules, err, filled = build_ladder_rules_with_standard_trace(
        elapsed_days=elapsed,
        sale_price=sale,
        base_profit=base_profit,
        final_margin_percent=final_margin_percent,
        action="priceTrace",
        trace_value=1,
        akaji_drop_percent=2,
        takane_rise_percent=1,
    )
    if not rules or filled == 0:
        return False, err or "目標到達価格を設定できませんでした"

    record["ladder_enabled"] = 1
    record["ladder_rules"] = ladder_rules_to_json(rules)
    record["価格改定"] = "ON"
    record["repricing_enabled"] = 1
    return True, ""
