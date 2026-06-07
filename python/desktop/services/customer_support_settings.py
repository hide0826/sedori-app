#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カスタマー対応AIの定型文設定（QSettings）。"""
from __future__ import annotations

from typing import Dict

_INTRO_KEY = "customer_support/intro_text"
_OUTRO_KEY = "customer_support/outro_text"


def _settings():
    from PySide6.QtCore import QSettings

    return QSettings("HIRIO", "DesktopApp")


def load_customer_support_settings() -> Dict[str, str]:
    s = _settings()
    return {
        "intro_text": (s.value(_INTRO_KEY, "") or "").strip(),
        "outro_text": (s.value(_OUTRO_KEY, "") or "").strip(),
    }


def save_customer_support_settings(intro_text: str, outro_text: str) -> None:
    s = _settings()
    s.setValue(_INTRO_KEY, (intro_text or "").strip())
    s.setValue(_OUTRO_KEY, (outro_text or "").strip())


def normalize_customer_name(customer_name: str) -> str:
    """入力から「様」付きの呼びかけ用の名前部分を取り出す。"""
    name = (customer_name or "").strip()
    if name.endswith("様"):
        name = name[:-1].strip()
    return name


def format_opening_greeting(customer_name: str, intro_text: str) -> str:
    """
    返信冒頭: 「○○様　○○ストア商品担当の○○です」形式。
    名前と最初のテキストがあるときは全角スペースで1行に繋ぐ。
    """
    name = normalize_customer_name(customer_name)
    intro = (intro_text or "").strip()
    if name and intro:
        return f"{name}様　{intro}"
    if name:
        return f"{name}様"
    return intro


def apply_intro_outro(
    body: str,
    intro_text: str,
    outro_text: str,
    customer_name: str = "",
) -> str:
    """生成本文の前後にカスタマー名・定型文を付与する。"""
    parts = []
    opening = format_opening_greeting(customer_name, intro_text)
    outro = (outro_text or "").strip()
    core = (body or "").strip()
    if opening:
        parts.append(opening)
    if core:
        parts.append(core)
    if outro:
        parts.append(outro)
    return "\n\n".join(parts)
