#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""併記店舗分離の単体テスト。"""
from __future__ import annotations

from services.combined_store_split_service import (
    build_split_names,
    detect_combined_brands,
    split_combined_store,
)
from database.store_db import StoreDatabase


def test_detect_brands():
    assert detect_combined_brands("ハードオフ・オフハウス久喜店") == ["HA", "OF"]
    assert detect_combined_brands("ハードオフ・ホビーオフ愛川店") == ["HA", "HO"]
    assert detect_combined_brands("ハードオフ三鷹店") == ["HA"]


def test_build_split_names_kuki():
    plan = build_split_names("ハードオフ・オフハウス久喜店")
    assert plan is not None
    assert [b.brand for b in plan.brands] == ["HA", "OF"]
    assert plan.brands[0].store_name == "ハードオフ久喜店"
    assert plan.brands[1].store_name == "オフハウス久喜店"


def test_build_split_names_with_space():
    plan = build_split_names("ハードオフ・オフハウス 杉戸店")
    assert plan is not None
    assert plan.brands[0].store_name == "ハードオフ 杉戸店"
    assert plan.brands[1].store_name == "オフハウス 杉戸店"


def test_split_store_reuses_coords(tmp_path):
    db = StoreDatabase(db_path=str(tmp_path / "split.db"))
    sid = db.add_store(
        {
            "store_name": "ハードオフ・オフハウス久喜店",
            "store_code": "HA-84",
            "address": "旧住所",
            "phone": "048-000-0000",
            "latitude": 36.06,
            "longitude": 139.67,
        }
    )
    store = db.get_store(sid)

    def fake_fetch(name: str):
        return {
            "address": f"{name}住所",
            "phone": "048-111-2222",
            "latitude": 99.0,
            "longitude": 99.0,
        }

    result = split_combined_store(db, store, fetch_info=fake_fetch)
    assert result.split_count == 1
    updated = db.get_store(sid)
    assert updated["store_name"] == "ハードオフ久喜店"
    assert updated["store_code"] == "HA-84"
    assert float(updated["latitude"]) == 36.06
    assert float(updated["longitude"]) == 139.67
    assert "ハードオフ久喜店住所" in str(updated.get("address") or "")

    stores = db.list_stores()
    names = {s["store_name"] for s in stores}
    assert "オフハウス久喜店" in names
    of_store = next(s for s in stores if s["store_name"] == "オフハウス久喜店")
    assert float(of_store["latitude"]) == 36.06
    assert str(of_store.get("store_code") or "").startswith("OF")
    db.close()
