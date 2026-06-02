#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DB一覧用: 月別運用・改定価格（TP0〜TP3）の入力状況サマリ。

経過済みの出品日数帯は月別運用ダイアログと同様に分母から除外する。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from desktop.utils.purchase_elapsed_days import calc_elapsed_days_for_purchase_record
    from desktop.utils.repricer_ladder_table import (
        REPRICER_DAY_RANGES,
        _is_ladder_row_elapsed_past,
        parse_ladder_rules_json,
    )
except ImportError:
    from utils.purchase_elapsed_days import calc_elapsed_days_for_purchase_record  # type: ignore
    from utils.repricer_ladder_table import (  # type: ignore
        REPRICER_DAY_RANGES,
        _is_ladder_row_elapsed_past,
        parse_ladder_rules_json,
    )


def is_repricing_enabled(record: Dict[str, Any]) -> bool:
    raw = record.get("repricing_enabled")
    if raw is None:
        flag = str(record.get("価格改定") or "ON").strip().lower()
        return flag not in ("0", "off", "false", "無効", "no")
    return str(raw).strip().lower() not in ("0", "off", "false", "no")


def is_ladder_mode(record: Dict[str, Any]) -> bool:
    raw = record.get("ladder_enabled")
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "on", "yes")


def _price_value_filled(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().replace(",", "")
    if not text:
        return False
    try:
        return float(text) > 0
    except (TypeError, ValueError):
        return False


def _ladder_target_filled(rule: Optional[Dict[str, Any]]) -> bool:
    if not rule:
        return False
    tp = rule.get("target_price")
    if tp is None:
        return False
    try:
        return float(tp) > 0
    except (TypeError, ValueError):
        return False


def summarize_repricing_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    仕入DBの「月別」「改定価格」列用サマリ。

    Returns:
        monthly_label, price_label, price_tooltip,
        repricing_on, ladder_on, price_complete,
        price_filled, price_total, past_band_count,
        filter_ladder_match, filter_incomplete
    """
    ladder_on = is_ladder_mode(record)
    repricing_on = is_repricing_enabled(record)

    out: Dict[str, Any] = {
        "repricing_on": repricing_on,
        "ladder_on": ladder_on,
        "monthly_label": "ON" if ladder_on else "—",
        "price_label": "—",
        "price_tooltip": "",
        "price_complete": True,
        "price_filled": 0,
        "price_total": 0,
        "past_band_count": 0,
        "filter_ladder_match": ladder_on,
        "filter_incomplete": False,
    }

    if not repricing_on:
        out["price_tooltip"] = "価格改定がOFFのため、改定価格の入力状況は対象外です。"
        return out

    if ladder_on:
        elapsed = calc_elapsed_days_for_purchase_record(record)
        rules = parse_ladder_rules_json(record.get("ladder_rules") or record.get("LadderRules"))
        rules_by_end: Dict[str, Dict[str, Any]] = {}
        for rule in rules:
            df = rule.get("days_from")
            if df is not None:
                rules_by_end[str(int(df))] = rule

        effective = 0
        filled = 0
        past = 0
        for _start, end_day in REPRICER_DAY_RANGES:
            if _is_ladder_row_elapsed_past(elapsed, end_day):
                past += 1
                continue
            effective += 1
            if _ladder_target_filled(rules_by_end.get(str(end_day))):
                filled += 1

        out["price_filled"] = filled
        out["price_total"] = effective
        out["past_band_count"] = past
        out["price_complete"] = effective > 0 and filled >= effective
        out["filter_incomplete"] = effective > 0 and filled < effective

        if effective == 0:
            out["price_label"] = "—"
            out["price_tooltip"] = (
                f"月別運用ON。経過済み{past}帯のみ（現在以降の対象帯がありません）。"
            )
        elif out["price_complete"]:
            out["price_label"] = "完了"
            out["price_tooltip"] = (
                f"月別運用: 現在以降{effective}帯すべてに目標到達価格あり。"
                f"（経過済み{past}帯は対象外）"
            )
        else:
            out["price_label"] = f"{filled}/{effective}"
            out["price_tooltip"] = (
                f"月別運用: 現在以降{effective}帯のうち{filled}帯に目標到達価格あり。"
                f"（経過済み{past}帯は対象外）"
            )
        return out

    # TP0〜TP3（4段）モード
    tp_vals = [
        record.get("TP0") or record.get("tp0"),
        record.get("TP1") or record.get("tp1"),
        record.get("TP2") or record.get("tp2"),
        record.get("TP3") or record.get("tp3"),
    ]
    filled = sum(1 for v in tp_vals if _price_value_filled(v))
    effective = 4
    out["price_filled"] = filled
    out["price_total"] = effective
    out["price_complete"] = filled >= effective
    out["filter_incomplete"] = filled < effective

    if out["price_complete"]:
        out["price_label"] = "完了"
        out["price_tooltip"] = "TP0〜TP3 の4段すべてに価格が入っています。"
    else:
        out["price_label"] = f"TP {filled}/{effective}"
        out["price_tooltip"] = f"TP0〜TP3: {filled}段に価格あり（全{effective}段）。"

    return out
