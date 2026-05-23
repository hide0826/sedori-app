#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ設定（QSettings）の読み書き。"""
from __future__ import annotations

from typing import Any, Dict

_MANDATORY_KEY = "flea_market/mandatory_text"
_ADDITIONAL_PROMPT_KEY = "flea_market/additional_prompt"


def _settings():
    from PySide6.QtCore import QSettings

    return QSettings("HIRIO", "DesktopApp")


def load_flea_market_ai_settings() -> Dict[str, str]:
    s = _settings()
    return {
        "mandatory_text": (s.value(_MANDATORY_KEY, "") or "").strip(),
        "additional_prompt": (s.value(_ADDITIONAL_PROMPT_KEY, "") or "").strip(),
    }


def save_flea_market_ai_settings(mandatory_text: str, additional_prompt: str) -> None:
    s = _settings()
    s.setValue(_MANDATORY_KEY, (mandatory_text or "").strip())
    s.setValue(_ADDITIONAL_PROMPT_KEY, (additional_prompt or "").strip())


def apply_mandatory_footer(text: str, mandatory_text: str) -> str:
    """生成文案の末尾に必ず含める文を連結する。"""
    base = (text or "").strip()
    footer = (mandatory_text or "").strip()
    if not footer:
        return base
    if footer in base:
        return base
    if base:
        return base + "\n\n" + footer
    return footer
