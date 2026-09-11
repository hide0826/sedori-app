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
