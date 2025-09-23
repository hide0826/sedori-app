from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any
import pandas as pd
import numpy as np
import re
import math
import json
from python.core.config import CONFIG_PATH

@dataclass
class RepriceOutputs:
    updated_df: pd.DataFrame
    excluded_df: pd.DataFrame
    log_df: pd.DataFrame
    q4_switched_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    date_unknown_df: pd.DataFrame = field(default_factory=pd.DataFrame)

def clean_sku(sku: str) -> str:
    if not sku or not isinstance(sku, str):
        return ""
    if sku.startswith('="') and sku.endswith('"'):
        sku = sku[2:-1]
    return sku.strip()

def parse_listing_date_from_sku(sku: str) -> datetime | None:
    try:
        if not sku or not isinstance(sku, str): return None
        sku = clean_sku(sku)
        if not sku: return None
        patterns = [
            (r'^(\d{4})_(\d{2})(\d{2})_', False),
            (r'^(\d{4})(\d{2})(\d{2})-', False),
            (r'^(\d{4})_(\d{2})_(\d{2})_', False),
            (r'^(\d{2})(\d{2})(\d{2})-', True),
            (r'pr_[^_]+_(\d{4})(\d{2})(\d{2})_', False)
        ]
        for pattern, is_yy in patterns:
            match = re.search(pattern, sku)
            if match:
                year = 2000 + int(match.group(1)) if is_yy else int(match.group(1))
                month, day = int(match.group(2)), int(match.group(3))
                return _create_date_if_valid(year, month, day)
        return None
    except Exception:
        return None

def _create_date_if_valid(year: int, month: int, day: int) -> datetime | None:
    try:
        if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31): return None
        return datetime(year, month, day)
    except ValueError:
        return None

def get_rule_for_days(days: int, rules: Dict[str, Any]) -> Dict[str, Any] | None:
    if days <= 0: return None
    
    # 経過日数がルールのキー（30, 60...）を超えない最大のものを探す
    # 例: 75日の場合、"60"のルールが適用される
    applicable_days = 0
    for rule_days_str in rules.keys():
        rule_days = int(rule_days_str)
        if rule_days <= days and rule_days > applicable_days:
            applicable_days = rule_days
            
    return rules.get(str(applicable_days))

def apply_repricing_rules(df: pd.DataFrame, today: datetime) -> RepriceOutputs:
    df = df.copy()

    # --- 1. 設定ファイル読み込み ---
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    rules = config.get("reprice_rules", {})
    q4_rule_enabled = config.get("q4_rule_enabled", True) # デフォルトは有効

    # --- 2. 前処理・データ準備 ---
    for col in ["SKU", "price", "akaji", "priceTrace"]:
        if col not in df.columns: df[col] = 0 if col != "SKU" else ""
    
    df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
    df['akaji'] = pd.to_numeric(df['akaji'], errors='coerce').fillna(0)
    df['priceTrace'] = pd.to_numeric(df['priceTrace'], errors='coerce').fillna(0).astype(int)

    df["listed_at"] = df["SKU"].apply(parse_listing_date_from_sku)
    df["days_since_listed"] = df["listed_at"].apply(lambda x: (today - x).days if pd.notna(x) else np.nan)
    
    # --- 3. 処理優先順位に基づく分類 ---
    log_records = []
    
    # 3.1: 365日超 → 対象外
    excluded_mask = df["days_since_listed"] > 365
    excluded_df = df[excluded_mask].copy()
    df = df[~excluded_mask]
    if not excluded_df.empty:
        for idx in excluded_df.index: log_records.append({'index': idx, 'sku': excluded_df.loc[idx, 'SKU'], 'days': excluded_df.loc[idx, 'days_since_listed'], 'action': 'exclude', 'reason': 'Over 365 days'})

    # 3.2: Q4商品特例 (10月第1週)
    q4_switched_df = pd.DataFrame()
    if q4_rule_enabled and today.month == 10 and today.day <= 7:
        q4_mask = df['SKU'].str.contains('Q4', na=False)
        if q4_mask.any():
            df.loc[q4_mask, "priceTrace"] = 1
            q4_switched_df = df[q4_mask].copy()
            for idx in q4_switched_df.index: log_records.append({'index': idx, 'sku': q4_switched_df.loc[idx, 'SKU'], 'days': q4_switched_df.loc[idx, 'days_since_listed'], 'action': 'priceTrace', 'reason': 'Q4 Special Rule'})

    # 3.3: 日付不明商品 → 据え置き
    date_unknown_mask = df["days_since_listed"].isna()
    date_unknown_df = df[date_unknown_mask].copy()
    df = df[~date_unknown_mask]
    if not date_unknown_df.empty:
        for idx in date_unknown_df.index: log_records.append({'index': idx, 'sku': date_unknown_df.loc[idx, 'SKU'], 'days': -1, 'action': 'maintain', 'reason': 'Date unknown'})

    # --- 4. 設定ルール適用 ---
    df['new_price'] = df['price'].copy()
    df['new_priceTrace'] = df['priceTrace'].copy()

    for index, row in df.iterrows():
        days = row['days_since_listed']
        rule = get_rule_for_days(days, rules)
        
        if not rule:
            log_records.append({'index': index, 'sku': row['SKU'], 'days': days, 'action': 'maintain', 'reason': 'No applicable rule'})
            continue

        action = rule.get("action")
        price = row['price']
        akaji = row['akaji']
        new_price = price
        reason = f"Rule for {days} days"

        if action == "priceTrace":
            df.loc[index, 'new_priceTrace'] = rule.get("priceTrace", row['priceTrace'])
        
        elif action and action.startswith("price_down_"):
            try:
                percentage = int(action.split('_')[-1])
                multiplier = 1 - (percentage / 100.0)
                new_price = round(price * multiplier)
                
                # 利益率ガード
                guard_price = math.ceil(akaji * 1.10)
                if new_price < guard_price:
                    new_price = guard_price
                    reason += f" ({percentage}% down -> Profit Guard Applied)"
                else:
                    reason += f" ({percentage}% down)"
            except (ValueError, IndexError):
                 log_records.append({'index': index, 'sku': row['SKU'], 'days': days, 'action': 'maintain', 'reason': f'Invalid price_down action: {action}'})
                 continue
        
        elif action == "price_down_ignore":
            new_price = round(price * 0.99)
            reason += " (Ignore Profit)"

        elif action == "exclude":
            # この行をDataFrameに追加してから元のDataFrameから削除
            excluded_df = pd.concat([excluded_df, row.to_frame().T])
            df.drop(index, inplace=True)
            reason = "Excluded by rule"
            # ループの次のイテレーションに進む
            log_records.append({'index': index, 'sku': row['SKU'], 'days': days, 'action': action, 'reason': reason})
            continue

        df.loc[index, 'new_price'] = new_price
        log_records.append({'index': index, 'sku': row['SKU'], 'days': days, 'action': action, 'reason': reason})

    # 'new_price'と'new_priceTrace'が存在する行のみ更新
    if 'new_price' in df.columns:
        df['price'] = df['new_price']
        df.drop(columns=['new_price'], inplace=True)
    if 'new_priceTrace' in df.columns:
        df['priceTrace'] = df['new_priceTrace']
        df.drop(columns=['new_priceTrace'], inplace=True)

    # --- 5. 出力編集 ---
    updated_df = pd.concat([df, date_unknown_df])
    log_df = pd.DataFrame(log_records)

    return RepriceOutputs(
        updated_df=updated_df,
        excluded_df=excluded_df,
        log_df=log_df,
        q4_switched_df=q4_switched_df,
        date_unknown_df=date_unknown_df
    )