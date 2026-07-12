#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""store_master_widget 純関数まわりの pytest（Track E store_master Phase 0 安全網）。UI 生成なし。"""

from __future__ import annotations

from pathlib import Path

from _source_symbol_loader import load_class_subset

from desktop.services.store_master_auto_register import NON_STORE_CODES, _normalize_entries

_STORE_DIALOGS = Path(__file__).resolve().parents[1] / "ui" / "store_master" / "store_dialogs.py"
_STORE_LIST = Path(__file__).resolve().parents[1] / "ui" / "store_master" / "store_list.py"
_ONLINE = Path(__file__).resolve().parents[1] / "ui" / "store_master" / "online.py"

StoreEditDialog = load_class_subset(
    _STORE_DIALOGS, "StoreEditDialog", ["_coerce_coordinate"]
)
StoreListWidget = load_class_subset(
    _STORE_LIST, "StoreListWidget", ["_store_has_coordinates"]
)
OnlinePlatformEditDialog = load_class_subset(
    _ONLINE, "OnlinePlatformEditDialog", ["_suggest_platform_tokens"]
)
FleaMarketEditDialog = load_class_subset(
    _ONLINE, "FleaMarketEditDialog", ["_suggest_tokens"]
)


def test_coerce_coordinate_empty_and_invalid():
    coerce = StoreEditDialog._coerce_coordinate
    assert coerce(None) is None
    assert coerce("") is None
    assert coerce("not-a-number") is None
    assert coerce([1, 2]) is None


def test_coerce_coordinate_numeric():
    coerce = StoreEditDialog._coerce_coordinate
    assert coerce(35.6812) == 35.6812
    assert coerce("139.7671") == 139.7671
    assert coerce(0) == 0.0
    assert coerce("-0.5") == -0.5


def test_store_has_coordinates_true_when_both_valid():
    has_coords = StoreListWidget._store_has_coordinates
    assert has_coords({"latitude": 35.0, "longitude": 139.0}) is True
    assert has_coords({"latitude": "35.0", "longitude": "139.0"}) is True
    assert has_coords({"latitude": 0, "longitude": 0}) is True


def test_store_has_coordinates_false_when_missing_or_invalid():
    has_coords = StoreListWidget._store_has_coordinates
    assert has_coords({}) is False
    assert has_coords({"latitude": 35.0}) is False
    assert has_coords({"longitude": 139.0}) is False
    assert has_coords({"latitude": "", "longitude": 139.0}) is False
    assert has_coords({"latitude": None, "longitude": 139.0}) is False
    assert has_coords({"latitude": "x", "longitude": 139.0}) is False
    assert has_coords({"latitude": 35.0, "longitude": "y"}) is False


def test_suggest_platform_tokens_known():
    suggest = OnlinePlatformEditDialog()._suggest_platform_tokens
    assert suggest("amazon") == ("AMZ", "AMZ")
    assert suggest("Amazon") == ("AMZ", "AMZ")
    assert suggest("楽天") == ("RKT", "RKT")
    assert suggest("メルカリ") == ("MRC", "MRC")
    assert suggest("ヤフオク") == ("YAO", "YAO")


def test_suggest_platform_tokens_fallback():
    suggest = OnlinePlatformEditDialog()._suggest_platform_tokens
    assert suggest("") == ("PLT", "PLT")
    assert suggest("   ") == ("PLT", "PLT")
    assert suggest("あいう") == ("PLT", "PLT")
    assert suggest("Shopify") == ("SHO", "SHO")
    assert suggest("AB") == ("ABX", "ABX")


def test_suggest_tokens_known_flea():
    suggest = FleaMarketEditDialog()._suggest_tokens
    assert suggest("メルカリ") == ("MRC", "MRC")
    assert suggest("mercari") == ("MRC", "MRC")
    assert suggest("ヤフオク") == ("YAO", "YAO")
    assert suggest("ラクマ") == ("RKM", "RKM")
    assert suggest("paypayフリマ") == ("PPF", "PPF")


def test_suggest_tokens_fallback():
    suggest = FleaMarketEditDialog()._suggest_tokens
    assert suggest("") == ("FRM", "FRM")
    assert suggest("あいう") == ("FRM", "FRM")
    assert suggest("Shopify") == ("SHO", "SHO")
    assert suggest("XY") == ("XYX", "XYX")


def test_normalize_entries_dedupes_and_skips_non_store():
    assert _normalize_entries([]) == []
    assert _normalize_entries([("  ", "店")]) == []
    for code in NON_STORE_CODES:
        assert _normalize_entries([(code, "無視")]) == []
    assert _normalize_entries([("S001", "店A"), ("S001", "店B")]) == [("S001", "店A")]
    assert _normalize_entries([("S001", ""), ("S001", "店A")]) == [("S001", "店A")]
    assert _normalize_entries([("S002", "")]) == [("S002", "S002")]
    assert _normalize_entries([(" S003 ", " 店C ")]) == [("S003", "店C")]
