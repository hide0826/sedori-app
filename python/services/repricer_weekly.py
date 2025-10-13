import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Tuple, NamedTuple
import json
import re
from python.core.config import CONFIG_PATH
from python.core.csv_utils import normalize_dataframe_for_cp932

def preprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrameの前処理: Excel数式記法の完全除去
    """
    print(f"[DEBUG preprocess] Called with shape: {df.shape}")
    
    # 処理前のサンプルを出力
    if len(df) > 0:
        print(f"[DEBUG preprocess] BEFORE - First row price (raw): {df['price'].iloc[0] if 'price' in df.columns else 'N/A'}")
        print(f"[DEBUG preprocess] BEFORE - First row conditionNote (raw): {df['conditionNote'].iloc[0] if 'conditionNote' in df.columns else 'N/A'}")
    
    # すべての列でExcel数式記法を除去（文字列列・数値列両方）
    for col in df.columns:
        if df[col].dtype == 'object':  # 文字列列
            df[col] = df[col].astype(str).str.replace(r'^="(.*)"$', r'\1', regex=True)
    
    # 処理後のサンプルを出力
    if len(df) > 0:
        print(f"[DEBUG preprocess] AFTER Excel formula removal - price: {df['price'].iloc[0] if 'price' in df.columns else 'N/A'}")
        print(f"[DEBUG preprocess] AFTER Excel formula removal - conditionNote: {df['conditionNote'].iloc[0] if 'conditionNote' in df.columns else 'N/A'}")
    
    # 数値列を明示的に変換
    numeric_cols = ['price', 'cost', 'akaji', 'takane', 'number', 'priceTrace', 
                    'leadtime', 'amazon-fee', 'shipping-price', 'profit']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            if len(df) > 0:
                print(f"[DEBUG preprocess] {col} after numeric conversion: {df[col].iloc[0]}")
    
    print(f"[DEBUG preprocess] Completed. Final shape: {df.shape}")
    return df


class RepriceOutputs(NamedTuple):
    log_df: pd.DataFrame
    updated_df: pd.DataFrame
    excluded_df: pd.DataFrame

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_days_since_listed(sku: str, today: datetime) -> int:
    """
    SKUから正規表現パターンのリストを使用して日付を抽出し、今日までの経過日数を計算する。
    日付が抽出できない場合は-1を返す。
    """
    # 将来のパターン追加を容易にするための正規表現リスト
    # パターンは優先順位の高い順に並べる
    patterns = [
        # 2024_08_28 or 2024_0828
        r"^(?P<year>\d{4})_(?P<month>\d{2})_?(?P<day>\d{2})",
        # 20250201-...
        r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-",
        # pr_..._20250217_...
        r"_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_",
        # 250518-... (YYMMDD形式)
        r"^(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})-",
    ]

    for pattern in patterns:
        match = re.search(pattern, sku)
        if match:
            try:
                parts = match.groupdict()
                year, month, day = int(parts["year"]), int(parts["month"]), int(parts["day"])
                
                # YYMMDD形式の場合、2000年代として解釈
                if len(parts["year"]) == 2:
                    year += 2000

                listed_date = datetime(year, month, day)
                return (today - listed_date).days
            except (ValueError, KeyError):
                continue
    
    return -1

def get_rule_for_days(days: int, rules: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """
    経過日数に応じたルールキーとルールデータを返す
    30日間隔設定システム対応
    """
    # 30日間隔でのルール検索: 30, 60, 90, ..., 360
    for days_key in [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360]:
        if days <= days_key:
            rule_key = str(days_key)
            if rule_key in rules:
                return rule_key, rules[rule_key]

    # 365日超過の場合は対象外
    return "over_365", {"action": "exclude", "priceTrace": 0}

def calculate_new_price_and_trace(price: float, akaji: float, rule: Dict[str, Any], days_since_listed: int, config: Dict[str, Any], current_price_trace: int) -> Tuple[str, str, float, int]:
    """
    最新仕様：6種類のアクション対応
    1. maintain: 維持（価格もTraceも変更なし）
    2. priceTrace: Traceのみ変更（価格は変更なし）
    3. price_down_1: 価格のみ1%値下げ（Traceは変更なし）
    4. price_down_2: 価格のみ2%値下げ（Traceは変更なし）
    5. profit_ignore_down: 価格のみ1%値下げ・ガード無視（Traceは変更なし）
    6. exclude: 対象外（変更なし）
    """
    action = rule["action"]
    reason = f"Rule for {days_since_listed} days ({action})"

    # 計算前にfloatに変換
    price = float(price)
    akaji = float(akaji)

    # デフォルト: 変更なし
    new_price = price
    new_price_trace = current_price_trace  # 現在値を維持

    if action == "maintain":
        # 価格変更なし、priceTraceも変更なし
        pass

    elif action == "priceTrace":
        # priceTraceのみ変更、価格は変更なし
        new_price_trace = rule.get("priceTrace", 0)

    elif action == "price_down_1":
        # 価格のみ1%値下げ、priceTraceは変更なし
        new_price = round(price * 0.99)
        guard_price = akaji * config.get("profit_guard_percentage", 1.1)
        if new_price < guard_price:
            new_price = round(guard_price)
            reason += " (Profit Guard Applied)"

    elif action == "price_down_2":
        # 価格のみ2%値下げ、priceTraceは変更なし
        new_price = round(price * 0.98)
        guard_price = akaji * config.get("profit_guard_percentage", 1.1)
        if new_price < guard_price:
            new_price = round(guard_price)
            reason += " (Profit Guard Applied)"

    elif action == "profit_ignore_down":
        # 価格のみ1%値下げ（利益率ガード無視）、priceTraceは変更なし
        new_price = round(price * 0.99)
        reason += " (Profit Guard Ignored)"

    elif action == "exclude":
        # 対象外、変更なし
        reason = f"Excluded: {days_since_listed} days (manual handling required)"

    return action, reason, new_price, new_price_trace

def apply_repricing_rules(df: pd.DataFrame, today: datetime) -> RepriceOutputs:
    """
    30日間隔価格改定システム - 最新仕様対応
    注: preprocessは呼び出し元（repricer.py）で実行済み
    """
    config = load_config()
    log_data = []
    updated_inventory_data = []
    excluded_inventory_data = []
    excluded_skus = set(config.get("excluded_skus", []))

    rules = config["reprice_rules"]

    for index, row in df.iterrows():
        sku = row.get("SKU", "")
        price = row.get("price", 0)
        akaji = row.get("akaji", 0)
        price_trace = row.get("priceTrace", 0)

        # 除外SKU処理
        if sku in excluded_skus:
            log_data.append({
                "sku": sku, "days": -1, "action": "exclude",
                "reason": "Excluded SKU", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        days_since_listed = get_days_since_listed(sku, today)

        # 日付不明の場合は維持
        if days_since_listed == -1:
            log_data.append({
                "sku": sku, "days": days_since_listed, "action": "maintain",
                "reason": "Date unknown (maintained)", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace
            })
            row_dict = row.to_dict()
            updated_inventory_data.append(row_dict)
            continue

        # 365日超過の商品は対象外
        if days_since_listed > 365:
            log_data.append({
                "sku": sku, "days": days_since_listed, "action": "exclude",
                "reason": "Over 365 days (manual handling required)", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        # ルール適用
        rule_key, rule = get_rule_for_days(days_since_listed, rules)
        action, reason, new_price, new_price_trace = calculate_new_price_and_trace(
            price, akaji, rule, days_since_listed, config, price_trace
        )

        log_data.append({
            "sku": sku, "days": days_since_listed, "action": action,
            "reason": reason, "price": price, "new_price": new_price,
            "priceTrace": price_trace, "new_priceTrace": new_price_trace
        })

        # Prister形式の全列を保持したまま価格とpriceTraceのみ更新
        row_dict = row.to_dict()
        if action == "exclude":
            excluded_inventory_data.append(row_dict)
        else:
            # 価格とpriceTraceの更新（Prister形式の16列すべてを保持）
            row_dict['price'] = new_price
            row_dict['priceTrace'] = new_price_trace
            updated_inventory_data.append(row_dict)

    log_df = pd.DataFrame(log_data)
    updated_df = pd.DataFrame(updated_inventory_data)
    excluded_df = pd.DataFrame(excluded_inventory_data)

    # CSV出力前の正規化を無効化（元ファイルのフォーマットを完全保持するため）
    # 元のバイト列ベースの処理に切り替えたため、ここでの文字列変換は不要
    # log_df = normalize_dataframe_for_cp932(log_df)
    # updated_df = normalize_dataframe_for_cp932(updated_df)
    # excluded_df = normalize_dataframe_for_cp932(excluded_df)

    return RepriceOutputs(log_df=log_df, updated_df=updated_df, excluded_df=excluded_df)