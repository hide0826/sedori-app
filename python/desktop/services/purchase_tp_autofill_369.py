#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DBの TP0〜TP3 を、SKU の 3/6/9 タグと 3-6-9 改定ルールの TP 利益保持率から自動補完する。

3-6-9 の「利益保持率(%)」は、改定ロジックに合わせ次のように解釈する（TP自動(369) 専用）:
  TP価格 = 損益分岐点 + (保持率/100) × (販売予定価格 − 損益分岐点)
  上限は常に販売予定価格（それ以上にはならない）。
  保持率 0% … 損益分岐点。100% … 販売予定に近い値。

※ 行ダイアログの「目標利益率から逆算」は purchase_row_edit_dialog 側（別式）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple


def _parse_number(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except (ValueError, TypeError):
        return 0.0


def ta_price_from_target_margin_percent(
    sale: float,
    current_profit: float,
    rate_percent: float,
) -> Optional[int]:
    """
    販売予定価格・見込み利益・目標利益率(%) から TP 価格を求める。
    PurchaseRowEditDialog と同じ式。
    """
    if sale <= 0 or rate_percent <= 0:
        return None
    r = rate_percent / 100.0
    denom = r - 0.89
    if abs(denom) < 1e-6:
        return None
    ta_price = (current_profit - 0.89 * sale) / denom
    if ta_price <= 0:
        return None
    return int(ta_price)


def detect_369_profile_from_sku(sku: str, default_profile: str) -> Tuple[str, bool]:
    """
    SKU から 3 / 6 / 9 プロファイルを判定。判定不可時は default_profile。
    services/repricer_weekly.detect_369_profile_from_sku と同一ロジック。
    """
    if not isinstance(sku, str):
        return default_profile, True
    text = sku.upper()
    patterns = [
        (r"(^|[-_])3([PN])?($|[-_])", "3"),
        (r"(^|[-_])6([PN])?($|[-_])", "6"),
        (r"(^|[-_])9([PN])?($|[-_])", "9"),
        (r"(3P|3N)", "3"),
        (r"(6P|6N)", "6"),
        (r"(9P|9N)", "9"),
    ]
    for pattern, profile in patterns:
        if re.search(pattern, text):
            return profile, False
    return default_profile, True


def _tp_field_empty(val: Any) -> bool:
    if val is None:
        return True
    s = str(val).strip()
    return not s or s == "-"


def break_even_float_for_record(record: Dict[str, Any]) -> Optional[float]:
    """損益分岐点を float で返す（計算優先、なければ列の値）。"""
    try:
        from desktop.services.purchase_break_even import compute_break_even_for_record
    except ImportError:
        from services.purchase_break_even import compute_break_even_for_record  # type: ignore

    be = compute_break_even_for_record(record)
    if be is not None and be > 0:
        return float(be)
    for key in ("損益分岐点", "break_even", "breakeven", "損益分岐"):
        raw = record.get(key)
        if raw in (None, ""):
            continue
        n = _parse_number(raw)
        if n > 0:
            return float(n)
    return None


def tp_price_from_repricer_retention_percent(
    planned_sale: float,
    break_even: float,
    rate_percent: float,
) -> Optional[int]:
    """
    保持率を「販売予定までのマージンのうち何割を残すか」として TP 価格に変換する。
    """
    if planned_sale <= 0:
        return None
    be = max(0.0, float(break_even))
    spread = planned_sale - be
    r = max(0.0, min(100.0, float(rate_percent))) / 100.0
    if spread <= 0:
        if be > 0:
            return int(round(min(planned_sale, be)))
        return int(round(planned_sale))
    tp = be + r * spread
    tp = min(tp, planned_sale)
    return int(round(tp))


def break_even_price_int_for_record(record: Dict[str, Any]) -> Optional[int]:
    """損益分岐点を整数円で返す。"""
    bf = break_even_float_for_record(record)
    if bf is not None and bf > 0:
        return int(round(bf))
    return None


def load_369_repricer_config(api_client: Any = None) -> Dict[str, Any]:
    """3-6-9 用の repricer 設定。API が使えなければ config/reprice_rules.json を読む。"""
    if api_client is not None:
        try:
            cfg = api_client.get_repricer_config("369")
            if isinstance(cfg, dict) and cfg.get("rule_profiles"):
                return cfg
        except Exception:
            pass
    try:
        from core.config import CONFIG_PATH

        path = CONFIG_PATH
    except ImportError:
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "config" / "reprice_rules.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fill_purchase_record_tp_from_369(record: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """
    空欄の TP のみ、3-6-9 ルールに基づき価格を入れる。1件でも更新したら True。
    """
    sku = str(record.get("SKU") or record.get("sku") or "").strip()
    if not sku:
        return False

    sale = _parse_number(
        record.get("販売予定価格") or record.get("expected_price") or record.get("価格")
    )

    if sale <= 0:
        return False

    be_float = break_even_float_for_record(record)

    default_profile = str(config.get("default_profile") or "6")
    profiles = config.get("rule_profiles") or {}
    profile, _ = detect_369_profile_from_sku(sku, default_profile)
    prof = profiles.get(profile) or profiles.get(str(profile)) or {}
    tp_rates = prof.get("tp_rates") or {}

    pairs = (
        ("TP0", "tp0", "tp0"),
        ("TP1", "tp1", "tp1"),
        ("TP2", "tp2", "tp2"),
        ("TP3", "tp3", "tp3"),
    )

    changed = False
    for disp_key, low_key, rate_key in pairs:
        existing = record.get(disp_key) or record.get(low_key)
        if not _tp_field_empty(existing):
            continue
        rate_percent = float(tp_rates.get(rate_key) or 0)
        if rate_percent > 0 and be_float is not None:
            price_int = tp_price_from_repricer_retention_percent(sale, be_float, rate_percent)
        elif rate_percent > 0:
            price_int = None
        else:
            price_int = break_even_price_int_for_record(record)

        if price_int is None and rate_percent > 0:
            price_int = break_even_price_int_for_record(record)
        if price_int is None:
            continue
        text = str(price_int)
        record[disp_key] = text
        record[low_key] = text
        changed = True
    return changed
