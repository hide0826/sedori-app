from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Tuple, List
import pandas as pd
import re

@dataclass
class RepriceOutputs:
    updated_df: pd.DataFrame           # 改定後CSV用
    red_list_df: pd.DataFrame          # 赤字商品
    long_term_df: pd.DataFrame         # 12ヶ月超の除外通知
    switched_to_trace_df: pd.DataFrame # 60日超でpriceTrace=1へ切替

def clean_sku(sku: str) -> str:
    """
    SKUから不要な文字列を除去する前処理
    - ="..." パターンを除去（Excel等からの読み込み対応）
    - 先頭の=" と末尾の" を削除
    """
    if not sku or not isinstance(sku, str):
        return ""

    # ="..." パターンを除去
    if sku.startswith('="') and sku.endswith('"'):
        sku = sku[2:-1]  # 先頭の=" と末尾の" を除去

    return sku.strip()


def parse_listing_date_from_sku(sku: str) -> datetime | None:
    """
    実際のSKU形式から日付を解析
    優先順位:
    1. YYYY_MMDD_xxxx → YYYY/MM/DD
    2. YYYYMMDD-xxxx → YYYY/MM/DD
    3. YYYY_MM_DD_xxxx → YYYY/MM/DD
    4. YYMMDD-xxxx → 20YY/MM/DD
    5. pr_xxxx_YYYYMMDD_xxxx → YYYYMMDD部分抽出
    6. その他は日付解析不可
    """
    try:
        if not sku or not isinstance(sku, str):
            return None

        # SKU前処理を適用
        sku = clean_sku(sku)
        if not sku:
            return None

        # パターン1: YYYY_MMDD_xxxx (例: 2024_0503_item)
        pattern1 = r'^(\d{4})_(\d{2})(\d{2})_'
        match = re.match(pattern1, sku)
        if match:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return _create_date_if_valid(year, month, day)

        # パターン2: YYYYMMDD-xxxx (例: 20240503-item)
        pattern2 = r'^(\d{4})(\d{2})(\d{2})-'
        match = re.match(pattern2, sku)
        if match:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return _create_date_if_valid(year, month, day)

        # パターン3: YYYY_MM_DD_xxxx (例: 2024_05_03_item)
        pattern3 = r'^(\d{4})_(\d{2})_(\d{2})_'
        match = re.match(pattern3, sku)
        if match:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return _create_date_if_valid(year, month, day)

        # パターン4: YYMMDD-xxxx (例: 240503-item) → 20YY年として解釈
        pattern4 = r'^(\d{2})(\d{2})(\d{2})-'
        match = re.match(pattern4, sku)
        if match:
            yy, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            year = 2000 + yy
            return _create_date_if_valid(year, month, day)

        # パターン5: pr_xxxx_YYYYMMDD_xxxx (例: pr_abc_20240503_def)
        pattern5 = r'pr_[^_]+_(\d{4})(\d{2})(\d{2})_'
        match = re.search(pattern5, sku)
        if match:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return _create_date_if_valid(year, month, day)

        # どのパターンにも一致しない場合
        return None
    except Exception:
        return None


def _create_date_if_valid(year: int, month: int, day: int) -> datetime | None:
    """日付の妥当性をチェックしてdatetimeオブジェクトを作成"""
    try:
        # 基本的な範囲チェック
        if year < 1900 or year > 2100:
            return None
        if month < 1 or month > 12:
            return None
        if day < 1 or day > 31:
            return None

        # datetimeで実際の日付妥当性をチェック（2月30日などを弾く）
        return datetime(year, month, day)
    except ValueError:
        # 無効な日付（例: 2月30日）
        return None

def weekly_reprice(df: pd.DataFrame, today: datetime) -> RepriceOutputs:
    df = df.copy()

    # 前提列（Plister在庫CSV想定）: SKU, price, akaji, priceTrace など
    for col in ["SKU", "price", "akaji"]:
        if col not in df.columns:
            df[col] = None

    # 出品日推定
    df["listed_at"] = df["SKU"].apply(parse_listing_date_from_sku)

    # None値を持つ行に対する安全な日数計算
    def calculate_days_since_listed(listed_at):
        if pd.isna(listed_at) or listed_at is None:
            return None
        return (today - listed_at).days

    df["days_since_listed"] = df["listed_at"].apply(calculate_days_since_listed)

    # 12ヶ月超（365日超）は対象外 → 通知用抽出（日付不明は除外）
    long_term_df = df[(df["days_since_listed"].notna()) & (df["days_since_listed"] > 365)].copy()

    # 60日超は改定しないで priceTrace=1 切替候補（日付不明は除外）
    switched_to_trace_df = df[(df["days_since_listed"].notna()) & (df["days_since_listed"] > 60) & (df["days_since_listed"] <= 365)].copy()
    if "priceTrace" not in df.columns:
        df["priceTrace"] = 0
    df.loc[switched_to_trace_df.index, "priceTrace"] = 1

    # 改定対象: 0～60日（日付不明商品は日付取得できない旨を記録して対象外）
    date_unknown_df = df[df["days_since_listed"].isna()].copy()
    target = df[(df["days_since_listed"].notna()) & (df["days_since_listed"] >= 0) & (df["days_since_listed"] <= 60)].copy()

    # 週次 ±1%（暫定：まずは -1% のみ適用する例。後で条件を詰める）
    target["new_price"] = (target["price"].astype(float) * 0.99).round(2)

    # 赤字（new_price < akaji）
    red_mask = target["new_price"] < target["akaji"].astype(float)
    red_list_df = target[red_mask].copy()

    # 改定反映（赤字は一旦 new_price にも反映しつつ、別CSVで把握）
    df.loc[target.index, "price"] = target["new_price"]

    # 12ヶ月超は改定しない（price据え置き）
    # switched_to_trace は上でpriceTrace=1に切替済み

    # 日付不明商品は価格据え置き、priceTrace=0のまま維持
    df.loc[date_unknown_df.index, "priceTrace"] = 0

    updated_df = df.copy()
    return RepriceOutputs(
        updated_df=updated_df,
        red_list_df=red_list_df,
        long_term_df=long_term_df,
        switched_to_trace_df=switched_to_trace_df
    )
