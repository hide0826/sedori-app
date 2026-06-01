#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DBレコードの経過日数（出品日 or 仕入れ日基準）を計算する。"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional, Tuple

try:
    from desktop.services.calculation_service import CalculationService
except ImportError:
    from services.calculation_service import CalculationService  # type: ignore


def parse_display_date_for_elapsed_days(value: Any) -> Optional[date]:
    """仕入DBの日付列（仕入れ日・出品日）を date に変換する。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    dt = CalculationService.parse_datetime_string(text)
    return dt.date() if dt else None


def calc_elapsed_days_for_purchase_record(record: Dict[str, Any]) -> Optional[int]:
    """出品日（未設定時は仕入れ日）から今日までの経過日数を返す。"""
    listed_raw = record.get("出品日") or record.get("listed_date")
    ref_date: Optional[date] = None
    if str(listed_raw or "").strip():
        ref_date = parse_display_date_for_elapsed_days(listed_raw)
    if ref_date is None:
        ref_date = parse_display_date_for_elapsed_days(
            record.get("仕入れ日") or record.get("purchase_date")
        )
    if ref_date is None:
        return None
    return max(0, (date.today() - ref_date).days)


def format_elapsed_days_for_purchase_record(record: Dict[str, Any]) -> Tuple[str, str]:
    """経過日数の表示文字列とツールチップを返す。"""
    days = calc_elapsed_days_for_purchase_record(record)
    if days is None:
        return "-", "出品日・仕入れ日が未設定、または日付形式を解釈できません。"

    listed_raw = record.get("出品日") or record.get("listed_date")
    if str(listed_raw or "").strip() and parse_display_date_for_elapsed_days(listed_raw):
        ref_label = f"出品日（{listed_raw}）"
    else:
        purchase_raw = record.get("仕入れ日") or record.get("purchase_date") or ""
        ref_label = f"仕入れ日（{purchase_raw}）"

    return f"{days} 日", f"{ref_label} を基準に、今日までの経過日数です。"
