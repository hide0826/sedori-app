#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月別（30日刻み）改定ルールの共通ロジック（PySide6 非依存）。

FastAPI（repricer_weekly）とデスクトップ UI の両方から利用する。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

REPRICER_DAY_RANGES: List[tuple[int, int]] = [
    (1, 30), (31, 60), (61, 90), (91, 120), (121, 150),
    (151, 180), (181, 210), (211, 240), (241, 270),
    (271, 300), (301, 330), (331, 360), (361, 999),
]

# 月別運用表の12行目（1始まり）= 331-360日帯（0始まり index 11）
LADDER_ROW_INDEX_331_360 = 11


def band_start_day_for_period_end(period_end: int) -> int:
    """ルールの days_from（帯の終端日）から、その帯の開始日を返す。"""
    for start, end in REPRICER_DAY_RANGES:
        if end == period_end:
            return start
    return 361 if period_end >= 999 else 1


def _is_ladder_row_elapsed_past(elapsed_days: Optional[int], end_day: int) -> bool:
    """経過日数が帯の終了日を超えていれば、その帯は編集不可（経過済み）。"""
    if elapsed_days is None:
        return False
    return elapsed_days > end_day


def parse_ladder_rules_json(raw: Any) -> List[Dict[str, Any]]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def ladder_rules_to_json(rules: List[Dict[str, Any]]) -> str:
    return json.dumps(rules, ensure_ascii=False)
