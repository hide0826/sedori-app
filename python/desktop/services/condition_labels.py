#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Amazon 出品コンディション番号 ↔ 表示ラベル（仕入DB・在庫CSV共通）

inventory_service / amazon_inventory_loader_service の CONDITION_MAP と整合。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# 番号 → 仕入DB等で使う日本語ラベル
AMAZON_CONDITION_NUM_TO_LABEL: Dict[int, str] = {
    1: "中古(ほぼ新品)",
    2: "中古(非常に良い)",
    3: "中古(良い)",
    4: "中古(可)",
    5: "コレクター商品(ほぼ新品)",
    6: "コレクター商品(非常に良い)",
    7: "コレクター商品(良い)",
    8: "コレクター商品(可)",
    10: "再生品",
    11: "新品(新品)",
}

AMAZON_CONDITION_LABEL_TO_NUM: Dict[str, int] = {
    label: num for num, label in AMAZON_CONDITION_NUM_TO_LABEL.items()
}
AMAZON_CONDITION_LABEL_TO_NUM["新品"] = 11


def _strip_condition_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def is_numeric_condition(value: Any) -> bool:
    text = _strip_condition_text(value)
    return bool(text) and text.isdigit()


def condition_code_from_value(value: Any) -> Optional[int]:
    """コンディション列の値から Amazon コンディション番号を取得。"""
    text = _strip_condition_text(value)
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in AMAZON_CONDITION_LABEL_TO_NUM:
        return AMAZON_CONDITION_LABEL_TO_NUM[text]
    return None


def normalize_condition_display(value: Any) -> str:
    """
    数値のみのコンディションを日本語ラベルへ変換。
    既にラベル形式ならそのまま返す。
    """
    text = _strip_condition_text(value)
    if not text:
        return ""
    if text.isdigit():
        num = int(text)
        return AMAZON_CONDITION_NUM_TO_LABEL.get(num, text)
    if text in AMAZON_CONDITION_LABEL_TO_NUM:
        return text
    if "中古(" in text or text.startswith("新品") or "コレクター" in text or text == "再生品":
        return text
    return text


def backfill_condition_label_in_record(record: Dict[str, Any]) -> None:
    """コンディション列が番号のみのとき、表示用ラベルへ補完（インプレース）。"""
    for key in ("コンディション", "condition"):
        raw = record.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        label = normalize_condition_display(raw)
        if label and label != str(raw).strip():
            record[key] = label
        elif label:
            record[key] = label
        code = condition_code_from_value(raw)
        if code is not None and not record.get("condition_code"):
            record["condition_code"] = code
        break
