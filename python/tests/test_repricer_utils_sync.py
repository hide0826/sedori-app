#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 正とデスクトップコピーの repricer ユーティリティ一致テスト。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_UTILS = ROOT / "desktop" / "utils"


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        pytest.fail(f"モジュールを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def api_tp_target():
    from utils import repricer_tp_target

    return repricer_tp_target


@pytest.fixture(scope="module")
def desktop_tp_target():
    return _load_module_from_path(
        "desktop_repricer_tp_target_sync_test",
        DESKTOP_UTILS / "repricer_tp_target.py",
    )


@pytest.fixture(scope="module")
def api_ladder_core():
    from utils import repricer_ladder_core

    return repricer_ladder_core


@pytest.fixture(scope="module")
def desktop_ladder_core():
    return _load_module_from_path(
        "desktop_repricer_ladder_core_sync_test",
        DESKTOP_UTILS / "repricer_ladder_core.py",
    )


@pytest.mark.parametrize(
    "tp_target,config,expected",
    [
        ("tp0_follow", {"tp0_floor_guard": False}, ("tp0", True, False)),
        ("tp0_maintain", {"tp0_floor_guard": True}, ("tp0", False, True)),
        ("tp1", {"tp0_floor_guard": True}, ("tp1", True, False)),
        ("tp0", {"tp0_gradual_follow": True, "tp0_floor_guard": False}, ("tp0", True, False)),
        ("tp0", {"tp0_floor_guard": True}, ("tp0", True, True)),
    ],
)
def test_resolve_tp_behavior_matches(api_tp_target, desktop_tp_target, tp_target, config, expected):
    assert api_tp_target.resolve_tp_behavior(tp_target, config) == expected
    assert desktop_tp_target.resolve_tp_behavior(tp_target, config) == expected


@pytest.mark.parametrize(
    "tp_target,config,expected",
    [
        ("tp0_follow", {}, "tp0_follow"),
        ("tp0_maintain", {}, "tp0_maintain"),
        ("tp0", {"tp0_gradual_follow": True}, "tp0_follow"),
        ("tp0", {"tp0_gradual_follow": False}, "tp0_maintain"),
        ("tp1", {}, "tp1"),
    ],
)
def test_normalize_legacy_tp_target_matches(api_tp_target, desktop_tp_target, tp_target, config, expected):
    assert api_tp_target.normalize_legacy_tp_target(tp_target, config) == expected
    assert desktop_tp_target.normalize_legacy_tp_target(tp_target, config) == expected


@pytest.mark.parametrize(
    "tp_target,expected",
    [
        ("tp0_follow", "tp0"),
        ("tp0_maintain", "tp0"),
        ("tp1", "tp1"),
        ("unknown", "tp0"),
    ],
)
def test_base_tp_tier_matches(api_tp_target, desktop_tp_target, tp_target, expected):
    assert api_tp_target.base_tp_tier(tp_target) == expected
    assert desktop_tp_target.base_tp_tier(tp_target) == expected


@pytest.mark.parametrize(
    "period_end,expected",
    [
        (30, 1),
        (60, 31),
        (90, 61),
        (360, 331),
        (999, 361),
        (45, 1),
    ],
)
def test_band_start_day_for_period_end_matches(api_ladder_core, desktop_ladder_core, period_end, expected):
    assert api_ladder_core.band_start_day_for_period_end(period_end) == expected
    assert desktop_ladder_core.band_start_day_for_period_end(period_end) == expected


@pytest.mark.parametrize(
    "raw,expected_len",
    [
        (None, 0),
        ("", 0),
        ("[]", 0),
        ('[{"action":"maintain"}]', 1),
        ([{"action": "maintain"}], 1),
        ("not-json", 0),
    ],
)
def test_parse_ladder_rules_json_matches(api_ladder_core, desktop_ladder_core, raw, expected_len):
    api_result = api_ladder_core.parse_ladder_rules_json(raw)
    desktop_result = desktop_ladder_core.parse_ladder_rules_json(raw)
    assert len(api_result) == expected_len
    assert api_result == desktop_result
