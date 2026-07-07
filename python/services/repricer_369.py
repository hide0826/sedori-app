import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from services.repricer_common import (
    ACTION_NAMES_JP,
    RepriceOutputs,
    detect_369_profile_from_sku,
    format_trace_value,
    get_days_since_listed,
    to_float_or_none,
)
from services.repricer_purchase_db import (
    csv_profit_from_inventory_row,
    is_repricing_off,
    load_ladder_map_from_purchase_db,
    load_repricing_enabled_map_from_purchase_db,
    load_tp_map_from_purchase_db,
)
from utils.repricer_ladder_core import band_start_day_for_period_end
from utils.repricer_tp_target import (
    base_tp_tier,
    format_tp_target_label,
    resolve_tp_behavior,
    tiers_match_for_tp_down,
)


def _get_tp_band(days_since_listed: int) -> Tuple[str, int]:
    if days_since_listed <= 90:
        return "tp0", 90
    if days_since_listed <= 180:
        return "tp1", 180
    if days_since_listed <= 270:
        return "tp2", 270
    return "tp3", 365


def _get_tp_floor(price: float, akaji: float, tp_rate: float) -> float:
    base = akaji if akaji and akaji > 0 else price
    return round(max(0.0, base) * (max(0.0, tp_rate) / 100.0))


def _apply_tp0_strong_floor_guard(
    price: float,
    new_price: int,
    final_akaji: int,
    tp_floor: int,
    use_db_tp: bool,
    tp_key: str,
    apply_floor_guard: bool,
    reason_tokens: List[str],
) -> Tuple[int, int]:
    """
    TP0床ガード（強制）: 価格・akaji を TP0 未満にさせない。既に下回っていれば価格を戻す。
    """
    if not apply_floor_guard or str(tp_key).lower() != "tp0" or not use_db_tp or tp_floor <= 0:
        return new_price, final_akaji
    floor = int(round(tp_floor))
    if price < floor:
        new_price = floor
        reason_tokens.append(
            f"TP0_GUARD: 現在価格{round(price)}円がTP0({floor}円)未満のため強制復帰"
        )
    elif new_price < floor:
        new_price = floor
        reason_tokens.append(f"TP0_GUARD: 改定価格をTP0({floor}円)で固定")
    final_akaji = max(floor, final_akaji)
    return new_price, final_akaji


def _get_profile_rule_for_days(days_since_listed: int, profile_rules: List[Dict[str, Any]]) -> Tuple[int, Dict[str, Any]]:
    """profile_rules(リスト)から経過日数に対応するルールを返す。"""
    if not isinstance(profile_rules, list) or not profile_rules:
        return -1, {"days_from": 999, "action": "maintain", "value": 0, "tp_target": "tp0", "akaji_drop_percent": 1, "takane_rise_percent": 0}
    sorted_rules = sorted(profile_rules, key=lambda r: int(r.get("days_from", 999)))
    for idx, rule in enumerate(sorted_rules):
        try:
            days_to = int(rule.get("days_from", 999))
        except Exception:
            days_to = 999
        if days_since_listed <= days_to:
            return idx, rule
    return len(sorted_rules) - 1, sorted_rules[-1]


def _parse_ladder_target_price(rule: Dict[str, Any]) -> Optional[float]:
    v = rule.get("target_price")
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _get_ladder_merged_period_end(
    current_idx: int,
    current_rule: Dict[str, Any],
    ladder_rules: List[Dict[str, Any]],
    action: str,
) -> int:
    """同一アクションかつ同一 target_price が連続する帯の終端日（days_from）。"""
    if current_idx < 0 or not ladder_rules:
        return int(current_rule.get("days_from", 999) or 999)
    sorted_rules = sorted(ladder_rules, key=lambda r: int(r.get("days_from", 999)))
    target = _parse_ladder_target_price(current_rule)
    end_day = int(current_rule.get("days_from", 999) or 999)
    for i in range(current_idx + 1, len(sorted_rules)):
        rule = sorted_rules[i]
        if str(rule.get("action", "maintain")) != action:
            break
        if _parse_ladder_target_price(rule) != target:
            break
        end_day = int(rule.get("days_from", end_day) or end_day)
    return end_day


def _get_ladder_down_period_end(
    current_idx: int, current_rule: Dict[str, Any], ladder_rules: List[Dict[str, Any]]
) -> int:
    """同一 tp_down かつ同一 target_price が連続する終端日。"""
    return _get_ladder_merged_period_end(current_idx, current_rule, ladder_rules, "tp_down")


def _apply_monthly_ladder_for_row(
    row: Any,
    days_since_listed: int,
    ladder_rules: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    月別運用（個別ラダー）で1行分の改定を適用。
    Returns: (kind, log_entry, row_dict_or_excluded)  kind in ('updated', 'excluded')
    """
    sku = row.get("SKU", "")
    if isinstance(sku, str) and sku.startswith('="') and sku.endswith('"'):
        sku = sku[2:-1]
    asin = row.get("ASIN", "")
    title = row.get("title", "")
    price = float(row.get("price", 0) or 0)
    akaji = float(row.get("akaji", 0) or 0)
    price_trace = row.get("priceTrace", 0)

    interval_days = max(1, int(config.get("interval_days", 7)))
    alert_cfg = config.get("alerts", {}) or {}
    alert_enabled = bool(alert_cfg.get("enabled", True))
    alert_prefix = str(alert_cfg.get("reason_prefix", "ALERT")).strip() or "ALERT"

    rule_idx, active_rule = _get_profile_rule_for_days(days_since_listed, ladder_rules)
    raw_action = str(active_rule.get("action", "maintain"))
    rule_trace_value = active_rule.get("value", 0)
    target_price = _parse_ladder_target_price(active_rule)
    period_end = int(active_rule.get("days_from", 999) or 999)
    if raw_action in ("tp_down", "priceTrace"):
        period_end = _get_ladder_merged_period_end(
            rule_idx, active_rule, ladder_rules, raw_action
        )

    akaji_drop_percent = int(active_rule.get("akaji_drop_percent", 1) or 1)
    akaji_drop_percent = min(10, max(1, akaji_drop_percent))
    takane_rise_percent = int(active_rule.get("takane_rise_percent", 0) or 0)
    takane_rise_percent = min(10, max(0, takane_rise_percent))

    action_jp = ACTION_NAMES_JP.get(raw_action, raw_action)
    reason_tokens = [
        f"{days_since_listed}日経過: 月別運用({action_jp})",
    ]
    if target_price is not None:
        reason_tokens.append(f"LADDER_PRICE: 目標{round(target_price)}円(帯終端{period_end}日)")
    else:
        reason_tokens.append("LADDER_PRICE: 目標価格未設定")

    keepa_min = to_float_or_none(row.get("keepa_min_same_condition"))
    new_price_trace = price_trace
    tp_floor = round(target_price) if target_price is not None else 0
    has_target = target_price is not None and target_price > 0

    if raw_action == "maintain":
        new_price = round(price)
    elif raw_action == "instant_reprice":
        band_start = band_start_day_for_period_end(period_end)
        if has_target and days_since_listed >= band_start:
            new_price = tp_floor
            reason_tokens.append(
                f"INSTANT: {band_start}日〜帯で目標{tp_floor}円へ即時改定"
            )
        else:
            new_price = round(price)
            if not has_target:
                reason_tokens.append("目標価格未設定のため価格維持")
            elif days_since_listed < band_start:
                reason_tokens.append(f"帯開始前({band_start}日未満)のため価格維持")
        new_price_trace = 0
    elif raw_action == "priceTrace":
        if has_target and price > tp_floor:
            remaining_days = max(0, period_end - days_since_listed)
            steps = max(1, math.ceil(remaining_days / interval_days))
            delta = (price - tp_floor) / steps if steps > 0 else 0
            new_price = max(tp_floor, round(price - delta))
            reason_tokens.append(
                f"LADDER_DAILY: {days_since_listed}日→{period_end}日で{tp_floor}へ段階調整"
            )
        else:
            new_price = round(price)
            if not has_target:
                reason_tokens.append("目標価格未設定のため価格維持")
        new_price_trace = rule_trace_value
    elif raw_action == "tp_down":
        if has_target:
            if keepa_min is None:
                start_price = price
                reason_tokens.append("KEEPA_MISSING: keepa_min_same_condition 未入力")
            elif keepa_min < tp_floor:
                start_price = tp_floor
                if alert_enabled:
                    reason_tokens.append(
                        f"{alert_prefix}: keepa_min({round(keepa_min)}) < 目標({tp_floor}) のため目標で固定"
                    )
            else:
                start_price = min(price, keepa_min)
            remaining_days = max(0, period_end - days_since_listed)
            steps = max(1, math.ceil(remaining_days / interval_days))
            delta = (start_price - tp_floor) / steps if steps > 0 else 0
            new_price = max(tp_floor, round(start_price - delta))
        else:
            new_price = round(price)
            reason_tokens.append("目標価格未設定のため価格維持")
    elif raw_action in ("price_down_1", "price_down_2", "price_down_3", "price_down_4"):
        down_percent = int(raw_action.replace("price_down_", ""))
        new_price = round(price * (1.0 - down_percent / 100.0))
    elif raw_action == "exclude":
        log_entry = {
            "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
            "reason": f"{days_since_listed}日経過: 月別運用・除外", "price": price,
            "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
            "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
            "csv_profit": csv_profit_from_inventory_row(row),
            "rule_action": raw_action, "tp_target": "", "akaji": akaji,
            "akaji_drop_percent": akaji_drop_percent, "keepa_min_same_condition": keepa_min,
            "tp_floor": tp_floor if has_target else None,
            "is_tp_floor_or_below": False, "tp_reach_status": "",
        }
        return "excluded", log_entry, row.to_dict()
    elif raw_action in ("price_down_ignore", "profit_ignore_down"):
        new_price = round(price * 0.99)
        reason_tokens.append("（利益ガード無視）")
    else:
        new_price = round(price)

    akaji_guard_from_price = round(new_price * (1.0 - akaji_drop_percent / 100.0))
    final_akaji = max(0, akaji_guard_from_price)
    if price > final_akaji and new_price <= final_akaji:
        new_price = final_akaji
        reason_tokens.append("akaji下限に到達（維持）")
    elif price <= final_akaji:
        new_price = round(price)
        reason_tokens.append(f"現在価格{round(price)}がakaji下限以下のため維持")

    final_takane = max(new_price, round(new_price * (1.0 + takane_rise_percent / 100.0)))
    is_tp_floor_or_below = bool(has_target and (new_price <= tp_floor or price <= tp_floor))
    tp_reach_status = ""
    if is_tp_floor_or_below:
        tp_reach_status = "期間外到達" if price <= tp_floor and days_since_listed < period_end else "期間到達"

    reason = " / ".join(reason_tokens)
    row_dict = row.to_dict()
    row_dict["price"] = new_price
    row_dict["priceTrace"] = new_price_trace
    row_dict["akaji"] = final_akaji
    row_dict["takane"] = final_takane
    log_entry = {
        "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": action_jp,
        "reason": reason, "price": price, "new_price": new_price,
        "priceTrace": price_trace, "new_priceTrace": new_price_trace,
        "priceTraceChange": (new_price_trace if raw_action == "priceTrace" else 0),
        "priceTraceChangeDisplay": (format_trace_value(new_price_trace) if raw_action == "priceTrace" else "無し"),
        "csv_profit": csv_profit_from_inventory_row(row),
        "rule_action": raw_action,
        "tp_target": "ladder",
        "akaji": final_akaji,
        "akaji_drop_percent": akaji_drop_percent,
        "takane": final_takane,
        "takane_rise_percent": takane_rise_percent,
        "keepa_min_same_condition": keepa_min,
        "tp_floor": tp_floor if has_target else None,
        "is_tp_floor_or_below": is_tp_floor_or_below,
        "tp_reach_status": tp_reach_status,
    }
    return "updated", log_entry, row_dict


def _get_tp_down_period_end(current_idx: int, current_rule: Dict[str, Any], profile_rules: List[Dict[str, Any]]) -> int:
    """同一アクション(tp_down)かつ同一TP指定が連続する終端日を返す。"""
    if current_idx < 0 or not profile_rules:
        return int(current_rule.get("days_from", 999) or 999)
    sorted_rules = sorted(profile_rules, key=lambda r: int(r.get("days_from", 999)))
    target_tp = base_tp_tier(str(current_rule.get("tp_target", "tp0")))
    end_day = int(current_rule.get("days_from", 999) or 999)
    for i in range(current_idx + 1, len(sorted_rules)):
        rule = sorted_rules[i]
        action = str(rule.get("action", "maintain"))
        tp_target = base_tp_tier(str(rule.get("tp_target", "tp0")))
        if action != "tp_down" or not tiers_match_for_tp_down(tp_target, target_tp):
            break
        end_day = int(rule.get("days_from", end_day) or end_day)
    return end_day


def apply_repricing_rules_369(df: pd.DataFrame, today: datetime, config: Dict[str, Any]) -> RepriceOutputs:
    log_data = []
    updated_inventory_data = []
    excluded_inventory_data = []
    excluded_skus = set(config.get("excluded_skus", []))
    profiles = config.get("rule_profiles", {})
    exception_rules = config.get("exception_reprice_rules", []) or []
    default_profile = str(config.get("default_profile", "6"))
    interval_days = max(1, int(config.get("interval_days", 7)))
    alert_cfg = config.get("alerts", {}) or {}
    alert_enabled = bool(alert_cfg.get("enabled", True))
    alert_prefix = str(alert_cfg.get("reason_prefix", "ALERT")).strip() or "ALERT"
    sku_candidates = []
    for _, _row in df.iterrows():
        _sku = _row.get("SKU", "")
        if isinstance(_sku, str) and _sku.startswith('="') and _sku.endswith('"'):
            _sku = _sku[2:-1]
        sku_candidates.append(str(_sku or "").strip())
    tp_map_by_sku = load_tp_map_from_purchase_db(sku_candidates)
    repricing_enabled_map_by_sku = load_repricing_enabled_map_from_purchase_db(sku_candidates)
    ladder_map_by_sku = load_ladder_map_from_purchase_db(sku_candidates)

    for _, row in df.iterrows():
        sku = row.get("SKU", "")
        if isinstance(sku, str) and sku.startswith('="') and sku.endswith('"'):
            sku = sku[2:-1]
        price = float(row.get("price", 0) or 0)
        akaji = float(row.get("akaji", 0) or 0)
        price_trace = row.get("priceTrace", 0)
        asin = row.get("ASIN", "")
        title = row.get("title", "")
        row_repricing_off = is_repricing_off(row.get("価格改定"))
        db_repricing_enabled = repricing_enabled_map_by_sku.get(str(sku).strip(), True)
        if row_repricing_off or not db_repricing_enabled:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "価格改定OFF（仕入DB設定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        if sku in excluded_skus:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "除外",
                "reason": "除外SKU（設定で除外指定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        days_since_listed = get_days_since_listed(sku, today)
        if days_since_listed == -1:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": -1, "action": "維持",
                "reason": "日付不明（維持）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            updated_inventory_data.append(row.to_dict())
            continue
        if days_since_listed > 365:
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
                "reason": f"{days_since_listed}日経過: 365日超過（要手動対応）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": csv_profit_from_inventory_row(row),
                "tp_floor": None,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue

        sku_key = str(sku).strip()
        ladder_bundle = ladder_map_by_sku.get(sku_key) or {}
        if ladder_bundle.get("enabled") and ladder_bundle.get("rules"):
            kind, log_entry, row_payload = _apply_monthly_ladder_for_row(
                row, days_since_listed, ladder_bundle["rules"], config
            )
            log_data.append(log_entry)
            if kind == "excluded":
                excluded_inventory_data.append(row_payload)
            else:
                updated_inventory_data.append(row_payload)
            continue

        profile, is_fallback = detect_369_profile_from_sku(str(sku), default_profile)
        profile_data = profiles.get(profile) or {}
        profile_rules = profile_data.get("reprice_rules", []) or []

        sku_key = str(sku).strip()
        db_tp_row = tp_map_by_sku.get(sku_key) or {}
        has_db_sku = sku_key in tp_map_by_sku
        has_any_db_tp = any(
            (v is not None and float(v) > 0)
            for v in [db_tp_row.get("tp0"), db_tp_row.get("tp1"), db_tp_row.get("tp2"), db_tp_row.get("tp3")]
        )

        fallback_to_profile6 = bool(is_fallback and has_db_sku and has_any_db_tp)
        using_exception_rules = bool(is_fallback and not fallback_to_profile6 and exception_rules)

        if fallback_to_profile6:
            profile = "6"
            profile_data = profiles.get(profile) or {}
            profile_rules = profile_data.get("reprice_rules", []) or []

        active_rules = exception_rules if using_exception_rules else profile_rules
        rule_idx, active_rule = _get_profile_rule_for_days(days_since_listed, active_rules)
        raw_action = str(active_rule.get("action", "maintain"))
        rule_trace_value = active_rule.get("value", 0)
        tp_key_default, period_end_default = _get_tp_band(days_since_listed)
        tp_target_raw = str(active_rule.get("tp_target", tp_key_default)).lower()
        tp_key, tp0_gradual_follow, tp0_floor_guard = resolve_tp_behavior(tp_target_raw, config)
        if tp_key not in ("tp0", "tp1", "tp2", "tp3"):
            tp_key = tp_key_default
        akaji_drop_percent = int(active_rule.get("akaji_drop_percent", 1) or 1)
        akaji_drop_percent = min(10, max(1, akaji_drop_percent))
        takane_rise_percent = int(active_rule.get("takane_rise_percent", 0) or 0)
        takane_rise_percent = min(10, max(0, takane_rise_percent))
        tp_rates = ((profiles.get(profile) or {}).get("tp_rates") or {})
        tp_rate = float(tp_rates.get(tp_key, 0) or 0)
        db_tp_value = (db_tp_row.get(tp_key))
        use_db_tp = db_tp_value is not None and db_tp_value > 0
        tp_floor = round(db_tp_value) if use_db_tp else _get_tp_floor(price, akaji, tp_rate)
        period_end = _get_tp_down_period_end(rule_idx, active_rule, active_rules) if raw_action == "tp_down" else period_end_default

        action_jp = ACTION_NAMES_JP.get(raw_action, raw_action)
        rule_label = "例外ルール" if using_exception_rules else f"{profile}ルール"
        if using_exception_rules:
            reason_tokens = [f"{days_since_listed}日経過: 3-6-9改定({rule_label}/{action_jp})"]
        else:
            reason_tokens = [f"{days_since_listed}日経過: 3-6-9改定({rule_label}/{format_tp_target_label(tp_target_raw)}/{action_jp})"]
        if is_fallback:
            if fallback_to_profile6:
                reason_tokens.append("PROFILE_FALLBACK: SKUタグ判定不可だが仕入DBのTP入力ありのため6ルール適用")
            elif using_exception_rules:
                reason_tokens.append("PROFILE_FALLBACK: SKUタグ判定不可のため例外タブルール適用")
            else:
                reason_tokens.append(f"PROFILE_FALLBACK: SKUタグ判定不可（例外ルール未設定のため{profile}ルール適用）")
        if use_db_tp:
            reason_tokens.append(f"TP_DB: 仕入DBの{tp_key.upper()}={tp_floor}を適用")
            if price <= tp_floor:
                reason_tokens.append(
                    f"{tp_key.upper()}は{round(tp_floor)}だが現在価格{round(price)}のためTP下限以下判定で{round(price)}維持"
                )
        else:
            reason_tokens.append(f"TP_RATE: {tp_key.upper()}={tp_rate}% で算出")

        keepa_min = to_float_or_none(row.get("keepa_min_same_condition"))
        new_price_trace = price_trace
        if raw_action == "maintain":
            new_price = round(price)
        elif raw_action == "priceTrace":
            if tp_key == "tp0" and not tp0_gradual_follow:
                new_price = round(price)
                reason_tokens.append("TP0（価格維持）: 段階的下げを行わず価格維持")
                if tp0_floor_guard and use_db_tp and tp_floor > 0 and price < tp_floor:
                    new_price = round(tp_floor)
                    reason_tokens.append(
                        f"TP0下限固定: 現在価格{round(price)}円 < TP0({round(tp_floor)}円) のため復帰"
                    )
            elif tp_key == "tp0" and tp0_gradual_follow and use_db_tp and tp_floor > 0:
                if price < tp_floor and tp0_floor_guard:
                    new_price = round(tp_floor)
                    reason_tokens.append(
                        f"TP0下限固定: 現在価格{round(price)}円 < TP0({round(tp_floor)}円) のため復帰"
                    )
                elif price > tp_floor:
                    remaining_days = max(0, period_end - days_since_listed)
                    steps = max(1, math.ceil(remaining_days / interval_days))
                    delta = (price - tp_floor) / steps if steps > 0 else 0
                    new_price = max(round(tp_floor), round(price - delta))
                    reason_tokens.append(
                        f"TP0（追従）: {days_since_listed}日→{period_end}日でTP0({round(tp_floor)})へ段階調整"
                    )
                else:
                    new_price = round(tp_floor)
                new_price_trace = rule_trace_value
            elif use_db_tp and tp_floor > 0 and price > tp_floor:
                remaining_days = max(0, period_end - days_since_listed)
                steps = max(1, math.ceil(remaining_days / interval_days))
                delta = (price - tp_floor) / steps if steps > 0 else 0
                new_price = max(tp_floor, round(price - delta))
                reason_tokens.append(
                    f"TP_DAILY: {days_since_listed}日→{period_end}日で{tp_floor}へ段階調整"
                )
            else:
                new_price = round(price)
            new_price_trace = rule_trace_value
        elif raw_action == "tp_down":
            if tp_key == "tp0" and not tp0_gradual_follow:
                new_price = round(price)
                reason_tokens.append("TP0（価格維持）: 段階的下げを行わず価格維持")
                if tp0_floor_guard and use_db_tp and tp_floor > 0 and price < tp_floor:
                    new_price = round(tp_floor)
                    reason_tokens.append(
                        f"TP0下限固定: 現在価格{round(price)}円 < TP0({round(tp_floor)}円) のため復帰"
                    )
            else:
                if keepa_min is None:
                    start_price = price
                    reason_tokens.append("KEEPA_MISSING: keepa_min_same_condition 未入力")
                elif keepa_min < tp_floor:
                    start_price = tp_floor
                    if alert_enabled:
                        reason_tokens.append(
                            f"{alert_prefix}: keepa_min({round(keepa_min)}) < {tp_key.upper()}_floor({tp_floor}) のためTP下限で固定"
                        )
                else:
                    start_price = min(price, keepa_min)
                remaining_days = max(0, period_end - days_since_listed)
                steps = max(1, math.ceil(remaining_days / interval_days))
                delta = (start_price - tp_floor) / steps if steps > 0 else 0
                new_price = max(tp_floor, round(start_price - delta))
        elif raw_action in ("price_down_1", "price_down_2", "price_down_3", "price_down_4"):
            down_percent = int(raw_action.replace("price_down_", ""))
            new_price = round(price * (1.0 - down_percent / 100.0))
        elif raw_action == "exclude":
            log_data.append({
                "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": "除外",
                "reason": f"{days_since_listed}日経過: 除外（ルール設定）", "price": price,
                "new_price": price, "priceTrace": price_trace, "new_priceTrace": price_trace,
                "priceTraceChange": 0, "priceTraceChangeDisplay": "無し",
                "csv_profit": csv_profit_from_inventory_row(row),
                "rule_action": raw_action, "tp_target": tp_key, "akaji": akaji,
                "akaji_drop_percent": akaji_drop_percent, "keepa_min_same_condition": keepa_min,
                "tp_floor": tp_floor,
                "is_tp_floor_or_below": False,
                "tp_reach_status": "",
            })
            excluded_inventory_data.append(row.to_dict())
            continue
        else:
            new_price = round(price)

        akaji_guard_from_price = round(new_price * (1.0 - akaji_drop_percent / 100.0))
        final_akaji = max(0, akaji_guard_from_price)
        skip_maintain_below = tp0_floor_guard and use_db_tp and tp_floor > 0 and price < tp_floor
        if price > final_akaji and new_price <= final_akaji:
            new_price = final_akaji
            reason_tokens.append("TP下限に到達（維持）")
        elif price <= final_akaji and not skip_maintain_below:
            new_price = round(price)
            reason_tokens.append(
                f"{tp_key.upper()}は{round(tp_floor)}だが現在価格{round(price)}のためTP下限以下判定で{round(price)}維持"
            )
        new_price, final_akaji = _apply_tp0_strong_floor_guard(
            price, new_price, final_akaji, int(round(tp_floor)), use_db_tp, tp_key, tp0_floor_guard, reason_tokens
        )
        final_takane = max(new_price, round(new_price * (1.0 + takane_rise_percent / 100.0)))
        is_tp_floor_or_below = bool(tp_floor and tp_floor > 0 and (new_price <= tp_floor or price <= tp_floor))
        tp_reach_status = ""
        if is_tp_floor_or_below:
            if price <= tp_floor and days_since_listed < period_end:
                tp_reach_status = "期間外到達"
            else:
                tp_reach_status = "期間到達"

        reason = " / ".join(reason_tokens)
        row_dict = row.to_dict()
        row_dict["price"] = new_price
        row_dict["priceTrace"] = new_price_trace
        row_dict["akaji"] = final_akaji
        row_dict["takane"] = final_takane
        updated_inventory_data.append(row_dict)
        log_data.append({
            "sku": sku, "asin": asin, "title": title, "days": days_since_listed, "action": action_jp,
            "reason": reason, "price": price, "new_price": new_price,
            "priceTrace": price_trace, "new_priceTrace": new_price_trace,
            "priceTraceChange": (new_price_trace if raw_action == "priceTrace" else 0),
            "priceTraceChangeDisplay": (format_trace_value(new_price_trace) if raw_action == "priceTrace" else "無し"),
            "csv_profit": csv_profit_from_inventory_row(row),
            "rule_action": raw_action,
            "tp_target": tp_target_raw,
            "akaji": final_akaji,
            "akaji_drop_percent": akaji_drop_percent,
            "takane": final_takane,
            "takane_rise_percent": takane_rise_percent,
            "keepa_min_same_condition": keepa_min,
            "tp_floor": tp_floor,
            "is_tp_floor_or_below": is_tp_floor_or_below,
            "tp_reach_status": tp_reach_status,
        })

    log_df = pd.DataFrame(log_data)
    updated_df = pd.DataFrame(updated_inventory_data)
    excluded_df = pd.DataFrame(excluded_inventory_data)
    items_list = log_df.to_dict(orient='records')
    return RepriceOutputs(log_df=log_df, updated_df=updated_df, excluded_df=excluded_df, items=items_list)
