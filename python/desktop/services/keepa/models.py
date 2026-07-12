#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keepa 関連のデータクラス・定数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Literal

# Keepa の画像キー用ベースURL（公式ドキュメント準拠）
IMAGE_BASE_URL = "https://images-na.ssl-images-amazon.com/images/I/"


@dataclass
class KeepaProductInfo:
    asin: str
    title: Optional[str]
    image_url: Optional[str]
    new_price: Optional[float]
    new_price_state: Literal["ok", "no_seller", "no_data"]
    used_like_new: Optional[float]
    used_like_new_state: Literal["ok", "no_seller", "no_data"]
    used_very_good: Optional[float]
    used_very_good_state: Literal["ok", "no_seller", "no_data"]
    used_good: Optional[float]
    used_good_state: Literal["ok", "no_seller", "no_data"]
    used_acceptable: Optional[float]
    used_acceptable_state: Literal["ok", "no_seller", "no_data"]
    sales_rank: Optional[int]
    category_name: Optional[str]


@dataclass
class KeepaOfferRow:
    """live offer 1件分（UI 表示用・円は fetch 時と同じスケール補正済み）。"""

    condition_label: str
    is_fba: bool
    is_amazon: bool
    seller_note: str
    price_jpy: int
    ship_jpy: int
    total_jpy: int
    seller_id: Optional[str] = None


@dataclass
class Keepa369AnalysisResult:
    """3-6-9ロジック用の解析結果"""

    window_days: int
    sales_drop_count: int
    inferred_sales_count: int
    total_effective_drop_count: int
    used_price_avg: Optional[float]
    used_price_range: Optional[float]
    used_offer_count_delta: Optional[int]
    condition_price_summary: Dict[str, Dict[str, Optional[float]]]
    ai_mode: str
    ai_adjustment_percent: float
    ai_reasoning: str
