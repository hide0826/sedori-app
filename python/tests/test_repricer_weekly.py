#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""repricer_weekly のスナップショット・単体テスト。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest

from conftest import (
    FIXED_TODAY,
    SNAPSHOT_369_EXTRA_FIELDS,
    SNAPSHOT_CORE_FIELDS,
)
from services.repricer_weekly import (
    apply_repricing_rules,
    detect_369_profile_from_sku,
    get_days_since_listed,
)


def _normalize_item(item: Dict[str, Any], extra_fields: tuple[str, ...] = ()) -> Dict[str, Any]:
    """スナップショット比較用に items 行を正規化する。"""
    fields = SNAPSHOT_CORE_FIELDS + extra_fields
    normalized: Dict[str, Any] = {}
    for key in fields:
        if key not in item:
            continue
        value = item[key]
        if isinstance(value, float):
            if value == int(value):
                normalized[key] = int(value)
            else:
                normalized[key] = round(value, 4)
        else:
            normalized[key] = value
    return normalized


def _normalize_items(
    items: List[Dict[str, Any]],
    extra_fields: tuple[str, ...] = (),
) -> List[Dict[str, Any]]:
    sorted_items = sorted(items, key=lambda row: str(row.get("sku", "")))
    return [_normalize_item(row, extra_fields) for row in sorted_items]


def _load_expected_snapshot(fixtures_dir: Path, filename: str) -> List[Dict[str, Any]]:
    path = fixtures_dir / filename
    if not path.exists():
        pytest.fail(
            f"期待値ファイルがありません: {path}\n"
            "初回は RECORD_SNAPSHOT=1 で pytest を実行して生成してください。"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _write_snapshot(fixtures_dir: Path, filename: str, data: List[Dict[str, Any]]) -> None:
    path = fixtures_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# --- 単体テスト ---


def test_get_days_since_listed() -> None:
    today = FIXED_TODAY
    assert get_days_since_listed("20250201-B0007RBX52-UM-1650-1", today) == 42
    assert get_days_since_listed('="20250201-B0007RBX52-UM-1650-1"', today) == 42
    assert get_days_since_listed("2024_08_28-ASIN-TEST", datetime(2024, 9, 27)) == 30
    assert get_days_since_listed("250518-ASIN-TEST", datetime(2025, 6, 17)) == 30
    assert get_days_since_listed("INVALID-SKU", today) == -1


def test_detect_369_profile_from_sku() -> None:
    assert detect_369_profile_from_sku("20240605-SS-20-1780-6P-007", "6") == ("6", False)
    assert detect_369_profile_from_sku("20240605-SS-20-1780-3N-001", "6") == ("3", False)
    assert detect_369_profile_from_sku("20240605-SS-20-1780-9P-002", "6") == ("9", False)
    assert detect_369_profile_from_sku("20250201-B0007RBX52-UM-1650-1", "6") == ("6", True)


# --- スナップショットテスト ---


def test_standard_mode_items_snapshot(
    inventory_df: pd.DataFrame,
    fixed_today: datetime,
    fixtures_dir: Path,
) -> None:
    outputs = apply_repricing_rules(inventory_df, today=fixed_today, mode="standard")
    actual = _normalize_items(outputs.items)

    if os.environ.get("RECORD_SNAPSHOT") == "1":
        _write_snapshot(fixtures_dir, "repricer_standard_expected.json", actual)
        pytest.skip("RECORD_SNAPSHOT=1: golden file を書き込みました")

    expected = _load_expected_snapshot(fixtures_dir, "repricer_standard_expected.json")
    assert actual == expected


def test_369_mode_items_snapshot(
    inventory_df: pd.DataFrame,
    fixed_today: datetime,
    fixtures_dir: Path,
) -> None:
    outputs = apply_repricing_rules(inventory_df, today=fixed_today, mode="369")
    actual = _normalize_items(outputs.items, SNAPSHOT_369_EXTRA_FIELDS)

    if os.environ.get("RECORD_SNAPSHOT") == "1":
        _write_snapshot(fixtures_dir, "repricer_369_expected.json", actual)
        pytest.skip("RECORD_SNAPSHOT=1: golden file を書き込みました")

    expected = _load_expected_snapshot(fixtures_dir, "repricer_369_expected.json")
    assert actual == expected


def test_standard_mode_summary_counts(
    inventory_df: pd.DataFrame,
    fixed_today: datetime,
) -> None:
    outputs = apply_repricing_rules(inventory_df, today=fixed_today, mode="standard")
    assert len(outputs.items) == 3
    assert len(outputs.updated_df) == 3
    assert len(outputs.excluded_df) == 0
