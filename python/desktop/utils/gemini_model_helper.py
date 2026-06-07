#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini モデル名の統一（HIRIO は常に最安の Flash モデルを使用）"""

from __future__ import annotations

from typing import List, Optional

# Google AI の Flash 系のうち、HIRIO 既定の最安モデル
CHEAPEST_GEMINI_FLASH_MODEL = "gemini-2.0-flash-lite"

# 404 等で利用不可のときに試す Flash 候補（安い順）
GEMINI_FLASH_MODEL_FALLBACKS: List[str] = [
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash",
]


def resolve_gemini_flash_model(configured: Optional[str] = None) -> str:
    """設定値に関わらず、HIRIO が使う Gemini Flash モデル名を返す。"""
    _ = configured  # 旧設定値は参照しない（常に最安 Flash に統一）
    return CHEAPEST_GEMINI_FLASH_MODEL


def gemini_flash_model_candidates(configured: Optional[str] = None) -> List[str]:
    """API テスト等で順に試す Flash モデル候補（重複なし）"""
    primary = resolve_gemini_flash_model(configured)
    ordered: List[str] = []
    for name in [primary, *GEMINI_FLASH_MODEL_FALLBACKS]:
        n = (name or "").strip()
        if n and n not in ordered:
            ordered.append(n)
    return ordered
