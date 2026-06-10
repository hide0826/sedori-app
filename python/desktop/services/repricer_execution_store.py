#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""価格改定の最終実行日時の保存・次回実行予定日の算出。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from PySide6.QtCore import QSettings

SETTINGS_ORG = "HIRIO"
SETTINGS_APP = "SedoriDesktopApp"
_LAST_EXEC_KEY_369 = "repricer/369/last_execution_at"


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def record_repricer_execution(mode: str = "369", executed_at: Optional[datetime] = None) -> None:
    """価格改定実行完了時に日時を保存する。"""
    if str(mode) != "369":
        return
    when = executed_at or datetime.now()
    _settings().setValue(_LAST_EXEC_KEY_369, when.isoformat(timespec="seconds"))
    _settings().sync()


def get_last_repricer_execution(mode: str = "369") -> Optional[datetime]:
    """最終価格改定実行日時を取得する。"""
    if str(mode) != "369":
        return None
    raw = _settings().value(_LAST_EXEC_KEY_369)
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def load_repricer_interval_days(mode: str = "369", api_client: Any = None) -> int:
    """改定ルールの共通設定「改定間隔(日)」を読み込む。"""
    if str(mode) != "369":
        return 7
    try:
        if api_client is not None:
            cfg = api_client.get_repricer_config("369")
            if isinstance(cfg, dict):
                return max(1, int(cfg.get("interval_days", 7) or 7))
    except Exception:
        pass
    try:
        from services.purchase_tp_autofill_369 import load_369_repricer_config

        cfg = load_369_repricer_config(api_client)
        if isinstance(cfg, dict):
            return max(1, int(cfg.get("interval_days", 7) or 7))
    except Exception:
        pass
    return 7


def build_repricer_schedule_info(
    *,
    mode: str = "369",
    api_client: Any = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """
    TOP表示用の次回価格改定予定情報。

    次回予定日 = 前回実行日 + 改定間隔(日)
    """
    interval_days = load_repricer_interval_days(mode=mode, api_client=api_client)
    last_dt = get_last_repricer_execution(mode=mode)
    ref_today = today or date.today()

    info: Dict[str, Any] = {
        "mode": mode,
        "interval_days": interval_days,
        "last_execution_at": None,
        "last_execution_display": None,
        "next_scheduled_date": None,
        "next_scheduled_display": None,
        "is_due": False,
        "has_execution_record": False,
    }

    if last_dt is None:
        return info

    info["has_execution_record"] = True
    info["last_execution_at"] = last_dt.isoformat(timespec="seconds")
    info["last_execution_display"] = last_dt.strftime("%Y-%m-%d %H:%M")

    next_date = last_dt.date() + timedelta(days=interval_days)
    info["next_scheduled_date"] = next_date.isoformat()
    info["next_scheduled_display"] = next_date.strftime("%Y-%m-%d")
    info["is_due"] = ref_today >= next_date
    return info
