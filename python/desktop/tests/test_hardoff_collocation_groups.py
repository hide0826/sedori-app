#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ハードオフ系統の併設グループ化テスト。"""
from __future__ import annotations

from services.hardoff_collocation_groups import (
    detect_hardoff_family_brand,
    group_hardoff_family_stores,
)


def _store(code, name, lat, lng, order=0):
    return {
        "id": abs(hash(code)) % 100000,
        "store_code": code,
        "store_name": name,
        "latitude": lat,
        "longitude": lng,
        "display_order": order,
    }


def test_detect_brand_from_code_and_name():
    assert detect_hardoff_family_brand({"store_code": "HA-14", "store_name": "x"}) == "HA"
    assert detect_hardoff_family_brand({"store_code": "HO-01", "store_name": "x"}) == "HO"
    assert detect_hardoff_family_brand({"store_code": "OF-02", "store_name": "x"}) == "OF"
    assert detect_hardoff_family_brand({"store_code": "", "store_name": "オフハウス多摩"}) == "OF"
    assert detect_hardoff_family_brand({"store_code": "SS-01", "store_name": "セカンド"}) is None


def test_group_within_30m_prefers_hardoff():
    stores = [
        _store("OF-13", "オフハウス冨里", 35.7490296, 140.3108565, 1),
        _store("HO-05", "ホビーオフ冨里", 35.7489047, 140.3109215, 2),
        _store("HA-18", "ハードオフ富里", 35.7489725, 140.3108172, 3),
        _store("SS-25", "セカンドストリート", 35.80, 140.40, 4),
    ]
    groups = group_hardoff_family_stores(stores, radius_m=30.0)
    # HA/HO/OF は1グループ、SS は別
    assert len(groups) == 2
    colloc = next(g for g in groups if g.extra_count == 2)
    assert colloc.representative["store_code"] == "HA-18"
    codes = [s["store_code"] for s in colloc.members]
    assert codes == ["HA-18", "HO-05", "OF-13"]


def test_do_not_group_farther_than_30m():
    stores = [
        _store("HA-01", "ハードオフA", 35.68, 139.76),
        _store("HO-01", "ホビーオフB", 35.69, 139.77),  # 十分遠い
    ]
    groups = group_hardoff_family_stores(stores, radius_m=30.0)
    assert len(groups) == 2
    assert all(g.extra_count == 0 for g in groups)


def test_collocation_toggle_label():
    from services.hardoff_collocation_groups import collocation_toggle_label

    assert collocation_toggle_label(1) == ""
    assert collocation_toggle_label(2) == "＋2店舗併設"
    assert collocation_toggle_label(3) == "＋3店舗併設"
    assert collocation_toggle_label(3, expanded=True) == "－3店舗"


def test_missing_coords_not_grouped():
    stores = [
        _store("HA-01", "ハードオフ", None, None),
        _store("HO-01", "ホビーオフ", None, None),
    ]
    groups = group_hardoff_family_stores(stores)
    assert len(groups) == 2
