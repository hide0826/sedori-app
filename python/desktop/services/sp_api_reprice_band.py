#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-6-9 ルール帯から「最安追従期間」かどうかを判定する。

無人ジョブで週次 3-6-9 と最安追従を排他分割するために使う。
desktop/services と python/services の名前衝突を避けるため、
日数・プロファイル判定はここでも完結させる。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _config_path() -> Path:
    # python/desktop/services -> repo/config
    return Path(__file__).resolve().parents[3] / "config" / "reprice_rules.json"


def load_369_config() -> Dict[str, Any]:
    path = _config_path()
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        return {}
    config.setdefault("default_profile", "6")
    config.setdefault("rule_profiles", {})
    return config


def _days_from_listed_text(listed_date: Optional[str], today: datetime) -> Optional[int]:
    """出品日文字列から経過日数。空や不正なら None。"""
    text = str(listed_date or "").strip()
    if not text or text.lower() in ("nan", "none"):
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    normalized = text.replace(".", "-").replace("/", "-")[:10]
    try:
        listed = datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError:
        compact = "".join(ch for ch in text if ch.isdigit())[:8]
        try:
            listed = datetime.strptime(compact, "%Y%m%d")
        except ValueError:
            return None
    return max(0, (today.date() - listed.date()).days)


def get_days_since_listed(
    sku: str,
    today: Optional[datetime] = None,
    listed_date: Optional[str] = None,
) -> int:
    """出品日があればその経過日数。無ければ SKU 埋め込み日付。読めなければ -1。"""
    now = today or datetime.now()
    from_listed = _days_from_listed_text(listed_date, now)
    if from_listed is not None:
        return from_listed
    text = str(sku or "")
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    patterns = [
        r"^(?P<year>\d{4})_(?P<month>\d{2})_?(?P<day>\d{2})",
        r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-",
        r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})(?=[A-Za-z])",
        r"^[a-z]+-(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})-",
        r"_(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_",
        r"^(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})-",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            parts = match.groupdict()
            year, month, day = int(parts["year"]), int(parts["month"]), int(parts["day"])
            if len(parts["year"]) == 2:
                year += 2000
            listed = datetime(year, month, day)
            return (now - listed).days
        except (ValueError, KeyError):
            continue
    return -1


def detect_369_profile_from_sku(sku: str, default_profile: str = "6") -> str:
    if not isinstance(sku, str):
        return default_profile
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
            return profile
    return default_profile


def is_follow_rule(rule: Optional[Mapping[str, Any]]) -> bool:
    """ルール1件が追従帯か。"""
    if not isinstance(rule, dict):
        return False
    action = str(rule.get("action") or "").strip()
    if action == "priceTrace":
        return True
    tp = str(rule.get("tp_target") or "").strip().lower()
    if tp.endswith("_follow") or tp == "tp0_follow":
        return True
    return False


def _profile_rules(config: Mapping[str, Any], profile: str) -> List[Dict[str, Any]]:
    profiles = config.get("rule_profiles") or {}
    if not isinstance(profiles, dict):
        return []
    block = profiles.get(str(profile)) or {}
    if not isinstance(block, dict):
        return []
    rules = block.get("reprice_rules")
    if isinstance(rules, list):
        return [r for r in rules if isinstance(r, dict)]
    return []


def _fallback_rules(config: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = config.get("reprice_rules")
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        out: List[Dict[str, Any]] = []
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            item = dict(value)
            try:
                item.setdefault("days_from", int(key))
            except (TypeError, ValueError):
                item.setdefault("days_from", 999)
            if "action" not in item:
                trace = int(item.get("priceTrace") or item.get("value") or 0)
                item["action"] = "priceTrace" if trace else "maintain"
            out.append(item)
        return out
    return []


def _rule_for_days(days: int, rules: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not rules:
        return {"days_from": 999, "action": "maintain", "tp_target": "tp0"}
    sorted_rules = sorted(rules, key=lambda r: int(r.get("days_from", 999) or 999))
    for rule in sorted_rules:
        try:
            days_to = int(rule.get("days_from", 999) or 999)
        except (TypeError, ValueError):
            days_to = 999
        if days <= days_to:
            return dict(rule)
    return dict(sorted_rules[-1])


def resolve_active_rule_for_sku(
    sku: str,
    *,
    config: Optional[Mapping[str, Any]] = None,
    today: Optional[datetime] = None,
    listed_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], int, str]:
    """
    SKU の現行ルール帯を返す。

    Returns:
        (rule, days_since_listed, profile)
    """
    cfg = dict(config or load_369_config())
    now = today or datetime.now()
    default_profile = str(cfg.get("default_profile") or "6")
    profile = detect_369_profile_from_sku(sku, default_profile)
    days = get_days_since_listed(sku, now, listed_date)
    rules = _profile_rules(cfg, profile) or _fallback_rules(cfg)
    rule = _rule_for_days(days if days >= 0 else 999, rules)
    return rule, days, profile


def sku_is_in_follow_band(
    sku: str,
    *,
    config: Optional[Mapping[str, Any]] = None,
    today: Optional[datetime] = None,
    listed_date: Optional[str] = None,
) -> bool:
    """SKU がいま追従期間か。出品日があれば SKU 日付より優先する。"""
    rule, days, _ = resolve_active_rule_for_sku(
        sku, config=config, today=today, listed_date=listed_date
    )
    if days < 0:
        return False
    return is_follow_rule(rule)


def partition_skus_by_follow_band(
    skus: Sequence[str],
    *,
    config: Optional[Mapping[str, Any]] = None,
    today: Optional[datetime] = None,
    listed_dates: Optional[Mapping[str, str]] = None,
) -> Dict[str, List[str]]:
    """SKU を follow / weekly に分割する。"""
    cfg = config or load_369_config()
    now = today or datetime.now()
    dates = listed_dates or {}
    follow: List[str] = []
    weekly: List[str] = []
    for raw in skus:
        sku = str(raw or "").strip()
        if not sku:
            continue
        if sku_is_in_follow_band(sku, config=cfg, today=now, listed_date=dates.get(sku)):
            follow.append(sku)
        else:
            weekly.append(sku)
    return {"follow": follow, "weekly": weekly}
