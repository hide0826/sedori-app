#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルート地図の併設店舗登録・確認済みヘルパーテスト。"""
from __future__ import annotations

from services.google_maps_service import (
    _brand_matches_place_name,
    _haversine_m,
    _normalize_name_key,
)
from ui.store_master.route_map_widget import (
    _markers_from_stores,
    _missing_hardoff_brands,
    _store_map_dict,
    _suggest_collocated_store_name,
)


def test_suggest_collocated_store_name_keeps_spacing():
    assert (
        _suggest_collocated_store_name("オフハウス 東所沢店", "HA")
        == "ハードオフ 東所沢店"
    )
    assert (
        _suggest_collocated_store_name("オフハウス東所沢店", "HA")
        == "ハードオフ東所沢店"
    )
    assert _suggest_collocated_store_name("ハードオフ久喜店", "OF") == "オフハウス久喜店"


def test_missing_hardoff_brands():
    assert _missing_hardoff_brands(["OF"]) == ["HA", "HO"]
    assert _missing_hardoff_brands(["HA", "OF"]) == ["HO"]
    assert _missing_hardoff_brands(["HA", "HO", "OF"]) == []


def test_store_map_dict_marks_hardoff_family():
    mapped = _store_map_dict(
        {
            "id": 73,
            "store_code": "OF-73",
            "store_name": "オフハウス 東所沢店",
            "latitude": 35.8,
            "longitude": 139.5,
            "tags": [{"id": 1, "name": "ハードオフ系"}],
            "collocation_checked": 0,
        }
    )
    assert mapped is not None
    assert mapped["is_hardoff_family"] is True
    assert mapped["member_brands"] == ["OF"]
    assert mapped["collocation_checked"] is False


def test_markers_aggregate_collocation_checked():
    stores = [
        {
            "id": 1,
            "store_code": "HA-1",
            "store_name": "ハードオフ テスト店",
            "latitude": 35.80000,
            "longitude": 139.50000,
            "collocation_checked": 0,
            "tags": [],
        },
        {
            "id": 2,
            "store_code": "OF-1",
            "store_name": "オフハウス テスト店",
            "latitude": 35.80001,
            "longitude": 139.50001,
            "collocation_checked": 1,
            "tags": [],
        },
    ]
    markers = _markers_from_stores(stores)
    assert len(markers) == 1
    assert markers[0]["is_hardoff_family"] is True
    assert markers[0]["collocation_checked"] is True
    assert set(markers[0]["member_brands"]) == {"HA", "OF"}


def test_brand_matches_and_distance_helpers():
    assert _brand_matches_place_name("HA", "ハードオフ板橋赤塚店")
    assert _brand_matches_place_name("HO", "ホビーオフ○○店")
    assert _brand_matches_place_name("OF", "オフハウス東所沢店")
    assert not _brand_matches_place_name("HA", "セカンドストリート")
    # 約0m
    assert _haversine_m(35.0, 139.0, 35.0, 139.0) < 1.0
    # だいたい 111m / 0.001度
    d = _haversine_m(35.0, 139.0, 35.001, 139.0)
    assert 90 < d < 130
    assert _normalize_name_key("ハードオフ 東所沢店") == _normalize_name_key(
        "ハードオフ東所沢店"
    )
