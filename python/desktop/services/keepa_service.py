#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Keepa API ラッパーサービス（後方互換エントリポイント）。

実装は services/keepa/ パッケージに分割済み。
"""

from __future__ import annotations

from .keepa import (
    KeepaService,
    KeepaProductInfo,
    KeepaOfferRow,
    Keepa369AnalysisResult,
)

__all__ = [
    "KeepaService",
    "KeepaProductInfo",
    "KeepaOfferRow",
    "Keepa369AnalysisResult",
]
