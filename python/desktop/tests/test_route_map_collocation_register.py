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
    _merge_cross_route_hardoff_markers,
    _missing_hardoff_brands,
    _order_groups_nearest_neighbor,
    _point_in_polygon,
    _rows_for_pick_order,
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
    members = markers[0].get("members") or []
    assert len(members) == 2
    assert {m["store_code"] for m in members} == {"HA-1", "OF-1"}
    assert all("id" in m and "store_name" in m for m in members)


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


def test_merge_cross_route_hardoff_markers_same_coords():
    """別ルートでも同一座標の HA/HO は1ピン（H3相当）にまとまる。"""
    ha11 = _store_map_dict(
        {
            "id": 51,
            "store_code": "HA-11",
            "store_name": "ハードオフ船橋習志野台",
            "latitude": 35.720909,
            "longitude": 140.0522627,
            "tags": [],
        }
    )
    ho02 = _store_map_dict(
        {
            "id": 50,
            "store_code": "HO-02",
            "store_name": "ホビーオフ船橋習志野台",
            "latitude": 35.720909,
            "longitude": 140.0522627,
            "tags": [],
        }
    )
    ha60 = _store_map_dict(
        {
            "id": 274,
            "store_code": "HA-60",
            "store_name": "ハードオフ 船橋習志野台店",
            "latitude": 35.720909,
            "longitude": 140.0522627,
            "tags": [],
        }
    )
    assert ha11 and ho02 and ha60
    # ルートA: HA+HO 併設、ルートB: HA 単独（実データと同じ分裂）
    route_a_markers = _markers_from_stores(
        [
            {
                "id": 51,
                "store_code": "HA-11",
                "store_name": "ハードオフ船橋習志野台",
                "latitude": 35.720909,
                "longitude": 140.0522627,
                "tags": [],
            },
            {
                "id": 50,
                "store_code": "HO-02",
                "store_name": "ホビーオフ船橋習志野台",
                "latitude": 35.720909,
                "longitude": 140.0522627,
                "tags": [],
            },
        ]
    )
    route_b_markers = _markers_from_stores(
        [
            {
                "id": 274,
                "store_code": "HA-60",
                "store_name": "ハードオフ 船橋習志野台店",
                "latitude": 35.720909,
                "longitude": 140.0522627,
                "tags": [],
            }
        ]
    )
    map_routes = [
        {"route_code": "A", "stores": route_a_markers},
        {"route_code": "B", "stores": route_b_markers},
    ]
    unassigned: list = []
    _merge_cross_route_hardoff_markers(map_routes, unassigned)

    visible_pins = [
        s
        for r in map_routes
        for s in (r.get("stores") or [])
        if not s.get("suppress_pin")
    ]
    stubs = [
        s
        for r in map_routes
        for s in (r.get("stores") or [])
        if s.get("suppress_pin")
    ]
    assert len(visible_pins) == 1
    assert len(stubs) == 1
    pin = visible_pins[0]
    assert pin["is_hardoff_family"] is True
    assert set(pin.get("member_codes") or []) >= {"HA-11", "HO-02", "HA-60"}
    assert pin.get("icon_key") == "hardoff3"


def test_rows_for_pick_order_unchecks_unselected():
    baseline = [
        {"store_code": "A", "store_name": "店A", "checked": True},
        {"store_code": "B", "store_name": "店B", "checked": True},
        {"store_code": "C", "store_name": "店C", "checked": True},
    ]
    rows = _rows_for_pick_order(baseline, ["B", "A"])
    assert [r["store_code"] for r in rows] == ["B", "A", "C"]
    assert rows[0]["checked"] is True
    assert rows[1]["checked"] is True
    assert rows[2]["checked"] is False


def test_rows_for_pick_order_empty_picks_all_skip():
    baseline = [
        {"store_code": "A", "checked": True},
        {"store_code": "B", "checked": False},
    ]
    rows = _rows_for_pick_order(baseline, [])
    assert [r["store_code"] for r in rows] == ["A", "B"]
    assert all(r["checked"] is False for r in rows)


def test_point_in_polygon_square():
    ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
    assert _point_in_polygon(0.5, 0.5, ring) is True
    assert _point_in_polygon(1.5, 0.5, ring) is False


def test_order_groups_nearest_neighbor_start_goal():
    groups = [
        {"key": "A", "codes": ["A"], "lat": 35.0, "lng": 139.0},
        {"key": "B", "codes": ["B"], "lat": 35.01, "lng": 139.0},
        {"key": "C", "codes": ["C"], "lat": 35.02, "lng": 139.0},
        {"key": "D", "codes": ["D1", "D2"], "lat": 35.03, "lng": 139.0},
    ]
    ordered = _order_groups_nearest_neighbor(groups, "A", "D")
    assert ordered[0] == "A"
    assert ordered[-2:] == ["D1", "D2"]
    assert set(ordered) == {"A", "B", "C", "D1", "D2"}
