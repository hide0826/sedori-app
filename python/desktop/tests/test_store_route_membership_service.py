#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""store_route_membership_service の pytest（UI なし）。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from desktop.database.store_db import StoreDatabase
from desktop.services.store_route_membership_service import (
    UNASSIGNED_COLUMN_KEY,
    add_store_to_route,
    apply_store_to_route_membership,
    build_kanban_columns_data,
    detach_store_from_route_if_not_selected,
    is_completely_unassigned,
    is_primary_in_route,
    move_store_to_route,
    parse_route_codes,
    remove_store_from_route,
    reorder_route_stores,
    store_in_route,
    unassign_store_completely,
)


@pytest.fixture
def temp_store_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "test_hirio.db")
        db = StoreDatabase(db_path=db_path)
        yield db
        db.close()


def _insert_store(db: StoreDatabase, **fields) -> int:
    data = {
        "store_name": fields.get("store_name", "テスト店"),
        "store_code": fields.get("store_code", "TST-01"),
        "affiliated_route_name": fields.get("affiliated_route_name"),
        "route_code": fields.get("route_code"),
        "display_order": fields.get("display_order", 0),
    }
    return db.add_store(data)


def test_parse_route_codes_splits_comma():
    store = {"route_code": "R001, R002 ,R003"}
    assert parse_route_codes(store) == ["R001", "R002", "R003"]


def test_store_in_route_by_code_or_name():
    store = {"affiliated_route_name": "成田ルート", "route_code": "R001,R002"}
    assert store_in_route(store, "成田ルート", "R001")
    assert store_in_route(store, "別名", "R002")
    assert not store_in_route(store, "別ルート", "R999")


def test_is_completely_unassigned():
    assert is_completely_unassigned({"affiliated_route_name": "", "route_code": ""})
    assert is_completely_unassigned({})
    assert not is_completely_unassigned({"route_code": "R001"})


def test_move_store_to_route(temp_store_db: StoreDatabase):
    sid = _insert_store(
        temp_store_db,
        store_code="HA-01",
        affiliated_route_name="Aルート",
        route_code="R001",
    )
    assert move_store_to_route(temp_store_db, sid, "Bルート", "R002")
    store = temp_store_db.get_store(sid)
    assert store["affiliated_route_name"] == "Bルート"
    assert store["route_code"] == "R002"


def test_add_store_to_route_keeps_primary(temp_store_db: StoreDatabase):
    sid = _insert_store(
        temp_store_db,
        store_code="HA-02",
        affiliated_route_name="Aルート",
        route_code="R001",
    )
    assert add_store_to_route(temp_store_db, sid, "Bルート", "R002")
    store = temp_store_db.get_store(sid)
    assert store["affiliated_route_name"] == "Aルート"
    assert parse_route_codes(store) == ["R001", "R002"]


def test_add_store_to_route_sets_primary_when_empty(temp_store_db: StoreDatabase):
    sid = _insert_store(temp_store_db, store_code="HA-03")
    assert add_store_to_route(temp_store_db, sid, "Bルート", "R002")
    store = temp_store_db.get_store(sid)
    assert store["affiliated_route_name"] == "Bルート"
    assert store["route_code"] == "R002"


def test_remove_store_from_route(temp_store_db: StoreDatabase):
    sid = _insert_store(
        temp_store_db,
        store_code="HA-04",
        affiliated_route_name="Aルート",
        route_code="R001,R002",
    )
    assert remove_store_from_route(temp_store_db, sid, "Aルート", "R001")
    store = temp_store_db.get_store(sid)
    assert store["route_code"] == "R002"
    assert store["affiliated_route_name"] is None


def test_unassign_store_completely(temp_store_db: StoreDatabase):
    sid = _insert_store(
        temp_store_db,
        store_code="HA-05",
        affiliated_route_name="Aルート",
        route_code="R001",
    )
    assert unassign_store_completely(temp_store_db, sid)
    store = temp_store_db.get_store(sid)
    assert is_completely_unassigned(store)


def test_reorder_route_stores(temp_store_db: StoreDatabase):
    s1 = _insert_store(
        temp_store_db,
        store_code="S1",
        affiliated_route_name="成田",
        route_code="R010",
        display_order=1,
    )
    s2 = _insert_store(
        temp_store_db,
        store_code="S2",
        affiliated_route_name="成田",
        route_code="R010",
        display_order=2,
    )
    assert reorder_route_stores(temp_store_db, "成田", ["S2", "S1"])
    assert temp_store_db.get_store(s2)["display_order"] == 1
    assert temp_store_db.get_store(s1)["display_order"] == 2


def test_apply_store_to_route_membership_duplicate_flag(temp_store_db: StoreDatabase):
    sid = _insert_store(
        temp_store_db,
        store_code="HA-06",
        affiliated_route_name="A",
        route_code="R001",
    )
    apply_store_to_route_membership(
        temp_store_db, sid, "B", "R002", allow_duplicate=True
    )
    store = temp_store_db.get_store(sid)
    assert store["affiliated_route_name"] == "A"
    assert "R002" in parse_route_codes(store)


def test_detach_store_from_route_if_not_selected(temp_store_db: StoreDatabase):
    sid = _insert_store(
        temp_store_db,
        store_code="HA-07",
        affiliated_route_name="成田",
        route_code="R010",
    )
    store = temp_store_db.get_store(sid)
    assert detach_store_from_route_if_not_selected(
        temp_store_db, store, "成田", "R010", selected_store_ids=[]
    )
    updated = temp_store_db.get_store(sid)
    assert is_completely_unassigned(updated)


def test_build_kanban_columns_data(temp_store_db: StoreDatabase):
    _insert_store(temp_store_db, store_code="U1", store_name="未所属店")
    _insert_store(
        temp_store_db,
        store_code="P1",
        store_name="主所属",
        affiliated_route_name="成田",
        route_code="R010",
    )
    _insert_store(
        temp_store_db,
        store_code="P2",
        store_name="副所属",
        affiliated_route_name="別ルート",
        route_code="R010,R011",
    )
    stores = temp_store_db.list_stores()
    routes = [
        {"route_name": "成田", "route_code": "R010"},
        {"route_name": "船橋", "route_code": "R011"},
    ]
    cols = build_kanban_columns_data(stores, routes)
    assert len(cols[UNASSIGNED_COLUMN_KEY]) == 1
    assert len(cols["R010"]) == 2
    assert len(cols["R011"]) == 1
    assert is_primary_in_route(cols["R010"][0], "成田") or is_primary_in_route(
        cols["R010"][1], "成田"
    )
