#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作業スナップショットの保存・呼出・削除。"""

from __future__ import annotations

from desktop.services.inventory_work_snapshot import (
    MAX_WORK_SNAPSHOTS,
    delete_work_snapshot,
    list_work_snapshots,
    load_work_snapshot,
    save_work_snapshot,
)


def test_save_list_load_and_modes_are_separate(tmp_path):
    save_work_snapshot("online", "ネットA", [{"商品名": "イヤホン"}], root=tmp_path)
    save_work_snapshot("store", "店舗A", [{"商品名": "本"}], root=tmp_path)
    online = list_work_snapshots("online", root=tmp_path)
    store = list_work_snapshots("store", root=tmp_path)
    assert len(online) == 1
    assert online[0]["name"] == "ネットA"
    assert len(store) == 1
    loaded = load_work_snapshot("online", online[0]["id"], root=tmp_path)
    assert loaded is not None
    assert loaded["records"][0]["商品名"] == "イヤホン"


def test_delete_work_snapshot(tmp_path):
    meta = save_work_snapshot("online", "消す", [{"商品名": "A"}], root=tmp_path)
    delete_work_snapshot("online", meta["id"], root=tmp_path)
    assert list_work_snapshots("online", root=tmp_path) == []
    assert load_work_snapshot("online", meta["id"], root=tmp_path) is None


def test_keeps_only_latest_limit(tmp_path):
    last_id = ""
    for i in range(MAX_WORK_SNAPSHOTS + 3):
        meta = save_work_snapshot("store", f"n{i}", [{"i": i}], root=tmp_path)
        last_id = meta["id"]
    items = list_work_snapshots("store", root=tmp_path)
    assert len(items) == MAX_WORK_SNAPSHOTS
    assert items[0]["id"] == last_id
