from datetime import datetime
from typing import Any, Dict

import pandas as pd

from services.repricer_common import (
    ACTION_NAMES_JP,
    RepriceOutputs,
    calculate_new_price_and_trace,
    format_trace_value,
    get_days_since_listed,
    get_rule_for_days,
)
from services.repricer_purchase_db import (
    is_repricing_off,
    load_repricing_enabled_map_from_purchase_db,
)


def apply_standard_repricing_rules(
    df: pd.DataFrame,
    today: datetime,
    config: Dict[str, Any],
) -> RepriceOutputs:
    log_data = []
    updated_inventory_data = []
    excluded_inventory_data = []
    excluded_skus = set(config.get("excluded_skus", []))
    sku_candidates = []
    for _, _row in df.iterrows():
        _sku = _row.get("SKU", "")
        if isinstance(_sku, str) and _sku.startswith('="') and _sku.endswith('"'):
            _sku = _sku[2:-1]
        sku_candidates.append(str(_sku or "").strip())
    repricing_enabled_map_by_sku = load_repricing_enabled_map_from_purchase_db(sku_candidates)

    rules = config["reprice_rules"]

    for _, row in df.iterrows():
        sku = row.get("SKU", "")
        # SKUからExcel数式記法を削除（念のため）
        if isinstance(sku, str) and sku.startswith('="') and sku.endswith('"'):
            sku = sku[2:-1]  # =" と " を除去

        price = row.get("price", 0)
        akaji = row.get("akaji", 0)
        price_trace = row.get("priceTrace", 0)

        # 除外SKU処理
        if sku in excluded_skus:
            asin = row.get("ASIN", "")
            title = row.get("title", "")
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "除外SKU（設定で除外指定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"  # Traceを行わない
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        days_since_listed = get_days_since_listed(sku, today)

        # 日付不明の場合は維持
        if days_since_listed == -1:
            asin = row.get("ASIN", "")
            title = row.get("title", "")
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "維持",
                "reason": "日付不明（維持）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"  # Traceを行わない
            })
            row_dict = row.to_dict()
            updated_inventory_data.append(row_dict)
            continue

        # 365日超過の場合は対象外
        if days_since_listed > 365:
            asin = row.get("ASIN", "")
            title = row.get("title", "")
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
                "reason": f"{days_since_listed}日経過: 365日超過（要手動対応）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"  # Traceを行わない
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        # ルール適用
        try:
            rule_key, rule = get_rule_for_days(days_since_listed, rules)
            if not rule:
                # ルールが見つからない場合は維持
                rule = {"action": "maintain", "priceTrace": 0}
            action, reason, new_price, new_price_trace = calculate_new_price_and_trace(
                price, akaji, rule, days_since_listed, config, price_trace
            )
        except Exception as e:
            # ルール適用エラーの場合は維持
            print(f"[WARNING] ルール適用エラー (SKU: {sku}): {e}")
            action = "maintain"
            reason = f"ルール適用エラー（維持）: {str(e)}"
            new_price = price
            new_price_trace = price_trace

        # ASINとTitleを取得
        asin = row.get("ASIN", "")
        title = row.get("title", "")
        row_repricing_off = is_repricing_off(row.get("価格改定"))
        db_repricing_enabled = repricing_enabled_map_by_sku.get(str(sku).strip(), True)
        if row_repricing_off or not db_repricing_enabled:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "価格改定OFF（仕入DB設定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0,
                "priceTraceChangeDisplay": "無し"
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        # priceTraceChangeの計算と表示文字列の決定
        if action == "priceTrace":
            if new_price_trace != price_trace:
                price_trace_change = new_price_trace
                price_trace_change_display = format_trace_value(new_price_trace)
            else:
                price_trace_change = price_trace
                trace_name = format_trace_value(price_trace)
                price_trace_change_display = f"{trace_name}維持"
        else:
            price_trace_change = 0
            price_trace_change_display = "無し"

        if action == "priceTrace":
            print(f"[DEBUG priceTrace] SKU: {sku}, action: {action}, price_trace: {price_trace}, new_price_trace: {new_price_trace}, price_trace_change: {price_trace_change}, display: {price_trace_change_display}")

        action_jp = ACTION_NAMES_JP.get(action, action)
        akaji_value = "" if action == "price_down_ignore" else None

        log_data.append({
            "sku": sku, "asin": asin, "title": title, "days": days_since_listed,
            "action": action_jp, "reason": reason, "price": price, "new_price": new_price,
            "priceTrace": price_trace, "new_priceTrace": new_price_trace,
            "priceTraceChange": price_trace_change,
            "priceTraceChangeDisplay": price_trace_change_display,
            "akaji": akaji_value
        })

        row_dict = row.to_dict()
        if action == "exclude":
            excluded_inventory_data.append(row_dict)
        else:
            row_dict['price'] = new_price
            row_dict['priceTrace'] = new_price_trace
            if action == "price_down_ignore":
                row_dict['akaji'] = ""
            updated_inventory_data.append(row_dict)

    log_df = pd.DataFrame(log_data)
    updated_df = pd.DataFrame(updated_inventory_data)
    excluded_df = pd.DataFrame(excluded_inventory_data)
    items_list = log_df.to_dict(orient='records')

    return RepriceOutputs(log_df=log_df, updated_df=updated_df, excluded_df=excluded_df, items=items_list)
