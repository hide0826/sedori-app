#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-6-9 価格改定ルールの簡単プリセット定義と適用ロジック。

- 回転重視 / 利益重視 / バランス重視 … 3ルール・6ルールに共通適用
- 9ルール … 特殊商品向け固定設定（プリセット種別に関わらず同一）
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

PRESET_BALANCE = "balance"
PRESET_TURNOVER = "turnover"
PRESET_PROFIT = "profit"
PRESET_CUSTOM = "custom"

PRESET_LABELS: Dict[str, str] = {
    PRESET_BALANCE: "バランス重視",
    PRESET_TURNOVER: "回転重視",
    PRESET_PROFIT: "利益重視",
    PRESET_CUSTOM: "カスタム",
}

TP_SOURCE_AUTO = "auto_369"
TP_SOURCE_MANUAL = "manual"

DAYS_FROM_LIST = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 999]

TP_TIER_KEYS = ("tp0", "tp1", "tp2", "tp3")


def tp_source_column(tier_key: str) -> str:
    return f"{tier_key}_source"


def is_tp_tier_manual(record: Dict[str, Any], tier_key: str) -> bool:
    """手動入力とみなすか（未設定ソースで値ありも手動扱い＝既存データ保護）。"""
    src = str(record.get(tp_source_column(tier_key)) or "").strip().lower()
    if src == TP_SOURCE_MANUAL:
        return True
    if src == TP_SOURCE_AUTO:
        return False
    disp = record.get(tier_key.upper()) or record.get(tier_key)
    if disp is not None and str(disp).strip() and str(disp).strip() != "-":
        return True
    return False


def _tp_target_for_row_index(row_index: int, *, all_tp0: bool = False) -> str:
    if all_tp0:
        return "tp0"
    if row_index <= 2:
        return "tp0"
    if row_index <= 5:
        return "tp1"
    if row_index <= 8:
        return "tp2"
    return "tp3"


def _akaji_balance(row_index: int) -> int:
    if row_index <= 5:
        return 5
    if row_index <= 8:
        return 7
    return 10


def _akaji_turnover(row_index: int) -> int:
    if row_index <= 2:
        return 5
    if row_index <= 5:
        return 7
    if row_index <= 8:
        return 8
    return 10


def _akaji_profit(_row_index: int) -> int:
    return 2


def build_reprice_rules(
    *,
    action: str = "priceTrace",
    trace_value: int = 1,
    akaji_for_row: Callable[[int], int],
    takane_percent: int = 1,
    all_tp0: bool = False,
    last_row_action: Optional[str] = None,
    last_row_trace: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """13行分の reprice_rules リストを組み立てる。"""
    rules: List[Dict[str, Any]] = []
    for i, days_from in enumerate(DAYS_FROM_LIST):
        if days_from == 999:
            row_action = last_row_action if last_row_action is not None else "maintain"
            row_trace = last_row_trace if last_row_trace is not None else 4
        else:
            row_action = action
            row_trace = trace_value
        rules.append(
            {
                "days_from": days_from,
                "action": row_action,
                "value": row_trace,
                "tp_target": _tp_target_for_row_index(i, all_tp0=all_tp0),
                "akaji_drop_percent": akaji_for_row(i),
                "takane_rise_percent": takane_percent,
            }
        )
    return rules


def build_profile_9_rules() -> List[Dict[str, Any]]:
    """9ルール固定: 全期間 priceTrace / TP0 / akaji1% / takane1%。"""
    return build_reprice_rules(
        action="priceTrace",
        trace_value=1,
        akaji_for_row=lambda _i: 1,
        takane_percent=1,
        all_tp0=True,
        last_row_action="priceTrace",
        last_row_trace=1,
    )


def build_profile_9_tp_rates() -> Dict[str, float]:
    return {"tp0": 95.0, "tp1": 95.0, "tp2": 95.0, "tp3": 95.0}


PRESETS_36: Dict[str, Dict[str, Any]] = {
    PRESET_BALANCE: {
        "tp_rates": {"tp0": 95.0, "tp1": 75.0, "tp2": 60.0, "tp3": 10.0},
        "akaji_for_row": _akaji_balance,
    },
    PRESET_TURNOVER: {
        "tp_rates": {"tp0": 90.0, "tp1": 65.0, "tp2": 50.0, "tp3": 5.0},
        "akaji_for_row": _akaji_turnover,
    },
    PRESET_PROFIT: {
        "tp_rates": {"tp0": 95.0, "tp1": 80.0, "tp2": 65.0, "tp3": 15.0},
        "akaji_for_row": _akaji_profit,
    },
}


def build_rule_profiles_for_preset(preset_id: str) -> Dict[str, Any]:
    """プリセットIDから rule_profiles（3/6/9）を生成。"""
    profiles: Dict[str, Any] = {}
    if preset_id in PRESETS_36:
        spec = PRESETS_36[preset_id]
        rules = build_reprice_rules(
            akaji_for_row=spec["akaji_for_row"],
            takane_percent=1,
        )
        for profile_key in ("3", "6"):
            profiles[profile_key] = {
                "tp_rates": dict(spec["tp_rates"]),
                "reprice_rules": rules,
            }
    profiles["9"] = {
        "tp_rates": build_profile_9_tp_rates(),
        "reprice_rules": build_profile_9_rules(),
    }
    return profiles


def tp0_floor_guard_for_preset(preset_id: str) -> bool:
    """利益重視のみ TP0 を強制床（下回っていれば価格復帰）として扱う。"""
    return preset_id == PRESET_PROFIT


def apply_preset_to_config(config: Optional[Dict[str, Any]], preset_id: str) -> Dict[str, Any]:
    """既存設定を維持しつつ rule_profiles と repricer_preset_369 を更新。"""
    if preset_id not in PRESETS_36:
        raise ValueError(f"不明なプリセット: {preset_id}")
    cfg = dict(config or {})
    cfg["rule_profiles"] = build_rule_profiles_for_preset(preset_id)
    cfg["repricer_preset_369"] = preset_id
    cfg["tp0_floor_guard"] = tp0_floor_guard_for_preset(preset_id)
    return cfg


def batch_recalculate_auto_tp(config: Dict[str, Any]) -> Tuple[int, int]:
    """
    仕入DBのうち TPソースが auto_369 の帯だけ、保持率に基づき TP を再計算する。
    Returns: (更新件数, 処理対象件数)
    """
    try:
        from desktop.services.purchase_tp_autofill_369 import fill_purchase_record_tp_from_369
        from desktop.services.purchase_inventory_only import merge_purchase_history_db_into_display_records
        from database.purchase_db import PurchaseDatabase
        from database.product_purchase_db import ProductPurchaseDatabase
    except ImportError:
        from services.purchase_tp_autofill_369 import fill_purchase_record_tp_from_369  # type: ignore
        from services.purchase_inventory_only import merge_purchase_history_db_into_display_records  # type: ignore
        from database.purchase_db import PurchaseDatabase  # type: ignore
        from database.product_purchase_db import ProductPurchaseDatabase  # type: ignore

    records: List[Dict[str, Any]] = []
    try:
        snap_db = ProductPurchaseDatabase()
        snaps = snap_db.list_snapshots()
        if snaps:
            latest = snap_db.get_snapshot(int(snaps[0]["id"]))
            if latest:
                records = list(latest.get("data") or [])
    except Exception:
        records = []

    purchase_db = PurchaseDatabase()
    merged = merge_purchase_history_db_into_display_records(records, purchase_db)

    updated = 0
    for record in merged:
        if not fill_purchase_record_tp_from_369(record, config, force_auto_only=True):
            continue
        sku = str(record.get("SKU") or record.get("sku") or "").strip()
        if not sku:
            continue
        upsert_payload: Dict[str, Any] = {"sku": sku}
        for tier in TP_TIER_KEYS:
            val = record.get(tier.upper()) or record.get(tier) or ""
            upsert_payload[tier] = val
            upsert_payload[tp_source_column(tier)] = record.get(tp_source_column(tier)) or TP_SOURCE_AUTO
        try:
            purchase_db.upsert(upsert_payload)
            updated += 1
        except Exception:
            pass
    return updated, len(merged)
