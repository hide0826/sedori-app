#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""価格改定テスト用の共通フィクスチャ。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from core.config import BASE_DIR
from core.csv_utils import read_csv_with_fallback
from services.repricer_weekly import preprocess_dataframe

FIXED_TODAY = datetime(2025, 3, 15)
TEST_REPRICER_CSV = BASE_DIR / "pwa" / "test_repricer.csv"

# スナップショット比較の共通フィールド
SNAPSHOT_CORE_FIELDS = (
    "sku",
    "days",
    "action",
    "price",
    "new_price",
    "priceTrace",
    "new_priceTrace",
)

# 369 モードで追加される比較フィールド（存在する場合のみ）
SNAPSHOT_369_EXTRA_FIELDS = (
    "tp_floor",
    "is_tp_floor_or_below",
    "tp_reach_status",
)


@pytest.fixture
def fixed_today() -> datetime:
    return FIXED_TODAY


@pytest.fixture
def inventory_df() -> pd.DataFrame:
    if not TEST_REPRICER_CSV.exists():
        pytest.skip(f"テスト用 CSV が見つかりません: {TEST_REPRICER_CSV}")
    content = TEST_REPRICER_CSV.read_bytes()
    df = read_csv_with_fallback(content)
    return preprocess_dataframe(df)


@pytest.fixture(autouse=True)
def isolate_purchase_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """ローカル hirio.db の有無に依存しないよう仕入DBローダーを空に固定する。"""
    monkeypatch.setattr(
        "services.repricer_purchase_db.load_tp_map_from_purchase_db",
        lambda sku_list: {},
    )
    monkeypatch.setattr(
        "services.repricer_purchase_db.load_repricing_enabled_map_from_purchase_db",
        lambda sku_list: {},
    )
    monkeypatch.setattr(
        "services.repricer_purchase_db.load_ladder_map_from_purchase_db",
        lambda sku_list: {},
    )
    # ファサード経由の後方互換エイリアスも同様に空にする
    monkeypatch.setattr(
        "services.repricer_purchase_db._load_tp_map_from_purchase_db",
        lambda sku_list: {},
    )
    monkeypatch.setattr(
        "services.repricer_purchase_db._load_repricing_enabled_map_from_purchase_db",
        lambda sku_list: {},
    )
    monkeypatch.setattr(
        "services.repricer_purchase_db._load_ladder_map_from_purchase_db",
        lambda sku_list: {},
    )


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"
