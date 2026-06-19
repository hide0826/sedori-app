#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-6-9 改定の tp_target 解釈（TP0追従 / TP0価格維持 / TP0下限固定）。

FastAPI（repricer_weekly）とデスクトップ UI の両方から利用する。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

TP0_MAINTAIN = "tp0_maintain"
TP0_FOLLOW = "tp0_follow"

BASE_TP_TIERS = ("tp0", "tp1", "tp2", "tp3")

TP_TARGET_LABELS: Dict[str, str] = {
    TP0_MAINTAIN: "TP0（価格維持）",
    TP0_FOLLOW: "TP0（追従）",
    "tp0": "TP0",
    "tp1": "TP1",
    "tp2": "TP2",
    "tp3": "TP3",
}

TP_COMBO_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (TP0_MAINTAIN, TP_TARGET_LABELS[TP0_MAINTAIN]),
    (TP0_FOLLOW, TP_TARGET_LABELS[TP0_FOLLOW]),
    ("tp1", "TP1"),
    ("tp2", "TP2"),
    ("tp3", "TP3"),
)


def base_tp_tier(tp_target: str) -> str:
    """仕入DB参照用の基本帯（tp0〜tp3）を返す。"""
    raw = str(tp_target or "tp0").strip().lower()
    if raw in (TP0_MAINTAIN, TP0_FOLLOW, "tp0"):
        return "tp0"
    if raw in BASE_TP_TIERS:
        return raw
    return "tp0"


def resolve_tp_behavior(tp_target: str, config: Dict[str, Any]) -> Tuple[str, bool, bool]:
    """
    tp_target と共通設定から改定挙動を決定する。

    Returns:
        (base_tier, gradual_follow_at_tp0, apply_tp0_floor_guard)
    """
    raw = str(tp_target or "tp0").strip().lower()
    floor_guard = bool(config.get("tp0_floor_guard", False))

    if raw == TP0_FOLLOW:
        return "tp0", True, floor_guard
    if raw == TP0_MAINTAIN:
        return "tp0", False, floor_guard

    if raw == "tp0":
        gradual = config.get("tp0_gradual_follow")
        if gradual is None:
            # 旧設定互換: tp0_floor_guard=ON は追従ありだった
            gradual = bool(config.get("tp0_floor_guard", False))
        return "tp0", bool(gradual), floor_guard

    if raw in ("tp1", "tp2", "tp3"):
        return raw, True, False

    return "tp0", False, floor_guard


def normalize_legacy_tp_target(tp_target: str, config: Dict[str, Any]) -> str:
    """設定画面読込用: 旧 tp0 を tp0_maintain / tp0_follow に変換。"""
    raw = str(tp_target or "tp0").strip().lower()
    if raw in (TP0_MAINTAIN, TP0_FOLLOW, "tp1", "tp2", "tp3"):
        return raw
    if raw == "tp0":
        _, gradual, _ = resolve_tp_behavior("tp0", config)
        return TP0_FOLLOW if gradual else TP0_MAINTAIN
    return TP0_MAINTAIN


def format_tp_target_label(tp_target: str) -> str:
    raw = str(tp_target or "tp0").strip().lower()
    return TP_TARGET_LABELS.get(raw, raw.upper())


def tiers_match_for_tp_down(a: str, b: str) -> bool:
    """tp_down の連続帯マージ判定用。"""
    return base_tp_tier(a) == base_tp_tier(b)
