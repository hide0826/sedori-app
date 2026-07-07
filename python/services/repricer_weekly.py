"""
価格改定の公開 API ファサード。

実装は repricer_common / repricer_standard / repricer_369 / repricer_purchase_db に分割。
外部からは従来どおり services.repricer_weekly を import する。
"""

from datetime import datetime

import pandas as pd

from services.repricer_369 import apply_repricing_rules_369
from services.repricer_common import (
    ACTION_NAMES_JP,
    TRACE_VALUE_NAMES_JP,
    RepriceOutputs,
    calculate_new_price_and_trace,
    detect_369_profile_from_sku,
    format_trace_value,
    get_days_since_listed,
    get_rule_for_days,
    load_config,
    preprocess_dataframe,
    to_float_or_none,
)
from services.repricer_purchase_db import (
    _csv_profit_from_inventory_row,
    _is_repricing_off,
    _load_ladder_map_from_purchase_db,
    _load_repricing_enabled_map_from_purchase_db,
    _load_tp_map_from_purchase_db,
    _to_float_or_none_strict,
    csv_profit_from_inventory_row,
    is_repricing_off,
    load_ladder_map_from_purchase_db,
    load_repricing_enabled_map_from_purchase_db,
    load_tp_map_from_purchase_db,
)
from services.repricer_standard import apply_standard_repricing_rules


def apply_repricing_rules(df: pd.DataFrame, today: datetime, mode: str = "standard") -> RepriceOutputs:
    """
    30日間隔価格改定システム - 最新仕様対応
    注: preprocessは呼び出し元（repricer.py）で実行済み
    """
    normalized_mode = "369" if str(mode) == "369" else "standard"
    config = load_config(mode=normalized_mode)
    if normalized_mode == "369":
        return apply_repricing_rules_369(df, today, config)
    return apply_standard_repricing_rules(df, today, config)


__all__ = [
    "ACTION_NAMES_JP",
    "TRACE_VALUE_NAMES_JP",
    "RepriceOutputs",
    "apply_repricing_rules",
    "calculate_new_price_and_trace",
    "detect_369_profile_from_sku",
    "format_trace_value",
    "get_days_since_listed",
    "get_rule_for_days",
    "load_config",
    "preprocess_dataframe",
    "to_float_or_none",
    # 後方互換（テスト monkeypatch 用）
    "_load_tp_map_from_purchase_db",
    "_load_repricing_enabled_map_from_purchase_db",
    "_load_ladder_map_from_purchase_db",
    "_csv_profit_from_inventory_row",
    "_is_repricing_off",
    "_to_float_or_none_strict",
]
