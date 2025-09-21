from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Tuple, List
import pandas as pd

@dataclass
class RepriceOutputs:
    updated_df: pd.DataFrame           # 改定後CSV用
    red_list_df: pd.DataFrame          # 赤字商品
    long_term_df: pd.DataFrame         # 12ヶ月超の除外通知
    switched_to_trace_df: pd.DataFrame # 60日超でpriceTrace=1へ切替

def parse_listing_date_from_sku(sku: str) -> datetime | None:
    # 例: "250503-..." → 2025-05-03
    try:
        date_part = sku.split("-")[0]
        yy, mm, dd = date_part[:2], date_part[2:4], date_part[4:6]
        year = 2000 + int(yy)
        return datetime(year, int(mm), int(dd))
    except Exception:
        return None

def weekly_reprice(df: pd.DataFrame, today: datetime) -> RepriceOutputs:
    df = df.copy()

    # 前提列（Plister在庫CSV想定）: SKU, price, akaji, priceTrace など
    for col in ["SKU", "price", "akaji"]:
        if col not in df.columns:
            df[col] = None

    # 出品日推定
    df["listed_at"] = df["SKU"].apply(parse_listing_date_from_sku)
    df["days_since_listed"] = (today - df["listed_at"]).dt.days

    # 12ヶ月超（365日超）は対象外 → 通知用抽出
    long_term_df = df[df["days_since_listed"] > 365].copy()

    # 60日超は改定しないで priceTrace=1 切替候補
    switched_to_trace_df = df[(df["days_since_listed"] > 60) & (df["days_since_listed"] <= 365)].copy()
    if "priceTrace" not in df.columns:
        df["priceTrace"] = 0
    df.loc[switched_to_trace_df.index, "priceTrace"] = 1

    # 改定対象: 0～60日
    target = df[(df["days_since_listed"] >= 0) & (df["days_since_listed"] <= 60)].copy()

    # 週次 ±1%（暫定：まずは -1% のみ適用する例。後で条件を詰める）
    target["new_price"] = (target["price"].astype(float) * 0.99).round(2)

    # 赤字（new_price < akaji）
    red_mask = target["new_price"] < target["akaji"].astype(float)
    red_list_df = target[red_mask].copy()

    # 改定反映（赤字は一旦 new_price にも反映しつつ、別CSVで把握）
    df.loc[target.index, "price"] = target["new_price"]

    # 12ヶ月超は改定しない（price据え置き）
    # switched_to_trace は上でpriceTrace=1に切替済み

    updated_df = df.copy()
    return RepriceOutputs(
        updated_df=updated_df,
        red_list_df=red_list_df,
        long_term_df=long_term_df,
        switched_to_trace_df=switched_to_trace_df
    )
