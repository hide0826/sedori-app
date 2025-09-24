import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Tuple, NamedTuple
import json
import re
from python.core.config import CONFIG_PATH

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

def get_rule_for_days(days: int, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    経過日数に応じたルールを返す（ルールは昇順ソートされていること）
    """
    for rule in rules:
        if days <= rule["days_from"]:
            return rule
    return None

def calculate_new_price(price: float, akaji: float, cost: float, rule: Dict[str, Any], days_since_listed: int, config: Dict[str, Any]) -> Tuple[str, str, float]:
    action = rule["action"]
    reason = f"Rule for {days_since_listed} days ({action})"
    new_price = price # デフォルトは維持

    if action == "price_down_1":
        new_price = price - rule["value"]
    elif action == "price_down_2":
        new_price = price * (1 - rule["value"] / 100)
    elif action == "price_trace":
        new_price = akaji
    
    guard_price = akaji * config.get("profit_guard_percentage", 1.1)
    if new_price < guard_price:
        new_price = guard_price
        reason += " (Profit Guard Applied)"

    return action, reason, int(new_price)

def apply_repricing_rules(df: pd.DataFrame, today: datetime) -> RepriceOutputs:
    config = load_config()
    log_data = []
    updated_inventory_data = []
    excluded_inventory_data = []
    excluded_skus = set(config.get("excluded_skus", []))
    
    rules = config["reprice_rules"]
    # 防御的措置：ルールが古い辞書形式の場合、新しいリスト形式にその場で変換する
    if isinstance(rules, dict):
        rules_list = []
        for days, rule_details in rules.items():
            rule_details['days_from'] = int(days)
            rules_list.append(rule_details)
        rules = rules_list

    # ルールをdays_fromで昇順にソート
    sorted_rules = sorted(rules, key=lambda x: x["days_from"])

    for index, row in df.iterrows():
        sku = row.get("SKU", "")
        price = row.get("price", 0)
        akaji = row.get("akaji", 0)
        cost = row.get("cost", 0)

        if sku in excluded_skus:
            log_data.append({"sku": sku, "days": -1, "action": "exclude", "reason": "Excluded SKU", "price": price, "new_price": price})
            excluded_inventory_data.append(row.to_dict())
            continue

        days_since_listed = get_days_since_listed(sku, today)
        action = "maintain"
        reason = "No applicable rule"
        new_price = price

        if days_since_listed != -1:
            rule = get_rule_for_days(days_since_listed, sorted_rules)
            if rule:
                action, reason, new_price = calculate_new_price(price, akaji, cost, rule, days_since_listed, config)
        else:
            reason = "Date unknown"

        log_data.append({"sku": sku, "days": days_since_listed, "action": action, "reason": reason, "price": price, "new_price": new_price})

        row_dict = row.to_dict()
        if action == "exclude":
            excluded_inventory_data.append(row_dict)
        else:
            row_dict['price'] = new_price
            updated_inventory_data.append(row_dict)

    log_df = pd.DataFrame(log_data)
    updated_df = pd.DataFrame(updated_inventory_data)
    excluded_df = pd.DataFrame(excluded_inventory_data)

    return RepriceOutputs(log_df=log_df, updated_df=updated_df, excluded_df=excluded_df)