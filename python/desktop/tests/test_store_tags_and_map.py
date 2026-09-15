#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗タグ（複数）と地図ペイロードの単体テスト。"""
from __future__ import annotations

import os
import tempfile

import pytest

from database.store_db import StoreDatabase


@pytest.fixture()
def temp_store_db(tmp_path):
    db_path = str(tmp_path / "hirio_tags_test.db")
    db = StoreDatabase(db_path=db_path)
    yield db
    db.close()


def test_default_tags_seeded(temp_store_db: StoreDatabase):
    tags = temp_store_db.list_store_tags(active_only=True)
    names = {t["name"] for t in tags}
    assert "大型店舗" in names
    assert "値付け甘い" in names
    assert "あまり行かなくて良い" in names


def test_multiple_tags_on_store(temp_store_db: StoreDatabase):
    tags = temp_store_db.list_store_tags(active_only=True)
    by_name = {t["name"]: int(t["id"]) for t in tags}
    store_id = temp_store_db.add_store(
        {
            "store_name": "テスト大型店",
            "store_code": "TT-01",
            "affiliated_route_name": "テストルート",
            "route_code": "T1",
            "latitude": 35.68,
            "longitude": 139.76,
        }
    )
    temp_store_db.upsert_route("テストルート", "T1")
    ok = temp_store_db.set_store_tag_ids(
        store_id,
        [by_name["大型店舗"], by_name["値付け甘い"]],
    )
    assert ok is True

    store = temp_store_db.get_store(store_id)
    assert store is not None
    tag_names = [t["name"] for t in store.get("tags") or []]
    assert tag_names[0] == "大型店舗"  # 優先度が高い方が先頭
    assert "値付け甘い" in tag_names

    ids = temp_store_db.get_store_tag_ids(store_id)
    assert set(ids) == {by_name["大型店舗"], by_name["値付け甘い"]}


def test_get_map_payload_includes_tagged_stores(temp_store_db: StoreDatabase):
    tags = temp_store_db.list_store_tags(active_only=True)
    tag_id = int(tags[0]["id"])
    temp_store_db.upsert_route("地図ルート", "M1")
    sid = temp_store_db.add_store(
        {
            "store_name": "地図テスト店",
            "store_code": "MP-01",
            "affiliated_route_name": "地図ルート",
            "route_code": "M1",
            "latitude": 35.7,
            "longitude": 139.8,
            "display_order": 1,
        }
    )
    # display_order を明示更新（add_store が列を書かない場合がある）
    temp_store_db.update_store(sid, {"display_order": 1})
    temp_store_db.set_store_tag_ids(sid, [tag_id])

    payload = temp_store_db.get_map_payload()
    assert payload["tags"]
    routes = payload["routes"]
    assert any(r.get("route_code") == "M1" for r in routes)
    m1 = next(r for r in routes if r.get("route_code") == "M1")
    assert m1["stores"]
    assert m1["stores"][0]["tags"]


def test_decode_polyline_roundtrip_helper():
    from services.google_maps_directions_service import _decode_polyline

    # 東京付近の短いエンコード例（Google の既知サンプルに近い簡易）
    # _p~iF~ps|U_ulLnnqC_mqNvxq`@
    pts = _decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert len(pts) >= 2
    assert abs(pts[0][0] - 38.5) < 0.1


def test_store_map_dict_includes_icon_key():
    from ui.store_master.route_map_widget import _store_map_dict

    mapped = _store_map_dict(
        {
            "id": 1,
            "store_name": "ブックオフ川口店",
            "store_code": "BK-01",
            "latitude": 35.8,
            "longitude": 139.7,
            "tags": [{"id": 1, "name": "BOOKOFF系", "color": "#c62828"}],
        }
    )
    assert mapped is not None
    assert mapped["icon_key"] == "bookoff"

    hardoff = _store_map_dict(
        {
            "id": 2,
            "store_name": "ハードオフ久喜店",
            "store_code": "HA-01",
            "latitude": 35.8,
            "longitude": 139.7,
            "tags": [{"id": 2, "name": "ハードオフ系", "color": "#1565c0"}],
        }
    )
    assert hardoff is not None
    assert hardoff["icon_key"] == "hardoff1"


def test_leaflet_html_uses_store_labels_when_enabled():
    from services.store_brand_tag_service import MAP_ICON_DEFS
    from ui.store_master.route_map_widget import build_leaflet_html

    html = build_leaflet_html(
        {
            "routes": [],
            "unassigned": [],
            "tag_legend": [],
            "icon_legend": [{"key": "bookoff", "label": "BOOKOFF系", "bg": "#c62828"}],
            "map_icons": MAP_ICON_DEFS,
            "use_icons": True,
            "grayscale": True,
        }
    )
    assert "hirio-pin" in html
    assert "hirio-pin-text" in html
    assert "__HIRIO_UPDATE" in html
    assert "addIconMarker" in html


def test_leaflet_html_preserves_view_via_incremental_update():
    from ui.store_master.route_map_widget import RouteMapWidget, build_leaflet_html

    html = build_leaflet_html(
        {
            "routes": [],
            "unassigned": [],
            "tag_legend": [],
            "icon_legend": [],
            "map_icons": {},
            "use_icons": False,
            "grayscale": True,
            "saved_view": {"lat": 35.5, "lng": 139.4, "zoom": 12},
        }
    )
    assert "window.__HIRIO_UPDATE" in html
    assert "opts.fit" in html
    assert "HIRIO_MAP:" in html
    assert "document.title" in html

    assert RouteMapWidget._normalize_map_view(
        {"lat": 35.5, "lng": 139.4, "zoom": 12}
    ) == {"lat": 35.5, "lng": 139.4, "zoom": 12.0}
    assert RouteMapWidget._normalize_map_view({"lat": 999, "lng": 0, "zoom": 10}) is None
    assert RouteMapWidget._normalize_map_view(None) is None


def test_markers_from_stores_collapses_hardoff_family():
    from ui.store_master.route_map_widget import _markers_from_stores

    stores = [
        {
            "id": 1,
            "store_code": "OF-13",
            "store_name": "オフハウス冨里",
            "latitude": 35.7490296,
            "longitude": 140.3108565,
            "display_order": 1,
            "tags": [{"id": 1, "name": "ハードオフ系", "color": "#1565c0"}],
        },
        {
            "id": 2,
            "store_code": "HO-05",
            "store_name": "ホビーオフ冨里",
            "latitude": 35.7489047,
            "longitude": 140.3109215,
            "display_order": 2,
            "tags": [{"id": 1, "name": "ハードオフ系", "color": "#1565c0"}],
        },
        {
            "id": 3,
            "store_code": "HA-18",
            "store_name": "ハードオフ富里",
            "latitude": 35.7489725,
            "longitude": 140.3108172,
            "display_order": 3,
            "tags": [{"id": 1, "name": "ハードオフ系", "color": "#1565c0"}],
        },
        {
            "id": 4,
            "store_code": "SS-25",
            "store_name": "セカンドストリート",
            "latitude": 35.80,
            "longitude": 140.40,
            "display_order": 4,
            "tags": [{"id": 2, "name": "セカンドストリート系", "color": "#00897b"}],
        },
    ]
    markers = _markers_from_stores(stores)
    keys = {m["icon_key"] for m in markers}
    assert "hardoff3" in keys
    assert "secondstreet" in keys
    assert len(markers) == 2
    h3 = next(m for m in markers if m["icon_key"] == "hardoff3")
    assert len(h3["member_names"]) == 3
