#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""purchase_repricing_summary の pytest（Track A Phase 0 安全網）。"""

from __future__ import annotations

import json

from desktop.utils.purchase_repricing_summary import (
    is_ladder_mode,
    is_repricing_enabled,
    summarize_repricing_row,
)
from utils.repricer_ladder_core import REPRICER_DAY_RANGES


def test_is_repricing_enabled_defaults_on():
    assert is_repricing_enabled({}) is True
    assert is_repricing_enabled({"価格改定": "OFF"}) is False
    assert is_repricing_enabled({"repricing_enabled": 0}) is False


def test_is_ladder_mode():
    assert is_ladder_mode({}) is False
    assert is_ladder_mode({"ladder_enabled": 1}) is True
    assert is_ladder_mode({"ladder_enabled": "true"}) is True


def test_summarize_repricing_off():
    out = summarize_repricing_row({"価格改定": "OFF"})
    assert out["repricing_on"] is False
    assert out["price_label"] == "—"
    assert "OFF" in out["price_tooltip"]


def test_summarize_tp_partial():
    out = summarize_repricing_row(
        {
            "価格改定": "ON",
            "TP0": 1000,
            "TP1": 900,
            "TP2": "",
            "TP3": "",
        }
    )
    assert out["ladder_on"] is False
    assert out["price_label"] == "TP 2/4"
    assert out["price_filled"] == 2
    assert out["price_complete"] is False
    assert out["filter_incomplete"] is True


def test_summarize_ladder_complete(monkeypatch):
    """経過日なし（全帯対象）で全帯に target_price があれば完了。"""
    monkeypatch.setattr(
        "desktop.utils.purchase_repricing_summary.calc_elapsed_days_for_purchase_record",
        lambda _record: None,
    )
    rules = [
        {"days_from": end, "target_price": 1000 + i}
        for i, (_start, end) in enumerate(REPRICER_DAY_RANGES)
    ]
    out = summarize_repricing_row(
        {
            "価格改定": "ON",
            "ladder_enabled": 1,
            "ladder_rules": json.dumps(rules, ensure_ascii=False),
        }
    )
    assert out["ladder_on"] is True
    assert out["monthly_label"] == "ON"
    assert out["price_label"] == "完了"
    assert out["price_complete"] is True
    assert out["price_filled"] == len(REPRICER_DAY_RANGES)
    assert out["price_total"] == len(REPRICER_DAY_RANGES)
