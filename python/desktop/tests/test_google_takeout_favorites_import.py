#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google Takeout お気に入り CSV インポートの単体テスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from database.store_db import StoreDatabase
from services.google_takeout_favorites_import import (
    _DuplicateIndex,
    import_takeout_favorites,
    normalize_address,
    normalize_phone,
    normalize_store_name,
    parse_takeout_favorites_csv,
)


@pytest.fixture()
def temp_store_db(tmp_path):
    db = StoreDatabase(db_path=str(tmp_path / "takeout_import_test.db"))
    yield db
    db.close()


def test_normalize_store_name_ignores_spaces():
    a = normalize_store_name("トレジャーファクトリー 吉川店")
    b = normalize_store_name("トレジャーファクトリー吉川店")
    assert a == b


def test_normalize_phone_strips_symbols():
    assert normalize_phone("03-1234-5678") == "0312345678"
    assert normalize_phone("+81 3-1234-5678") == "0312345678"


def test_normalize_address_strips_spaces_and_postal():
    a = normalize_address("〒100-0001 東京都 千代田区1-1")
    b = normalize_address("東京都千代田区1-1")
    assert a == b


def test_parse_takeout_csv(tmp_path):
    csv_path = tmp_path / "fav.csv"
    csv_path.write_text(
        "タイトル,メモ,URL,タグ,コメント\n"
        ",,,,\n"
        "ハードオフ多摩和田店,,https://maps.example/1,,\n"
        "オフハウス 多摩和田店,,https://maps.example/2,,\n",
        encoding="utf-8-sig",
    )
    rows = parse_takeout_favorites_csv(csv_path)
    assert len(rows) == 2
    assert rows[0].title == "ハードオフ多摩和田店"


def test_duplicate_by_name_and_phone():
    existing = [
        {
            "id": 1,
            "store_name": "ハードオフ多摩和田店",
            "phone": "042-111-2222",
            "address": "東京都多摩市和田1-1",
            "latitude": 35.63,
            "longitude": 139.45,
        }
    ]
    index = _DuplicateIndex(existing)
    dup = index.find_duplicate(title="ハードオフ 多摩和田店")
    assert dup is not None
    assert "店舗名" in dup[1]

    dup2 = index.find_duplicate(
        title="全然違う店名",
        phone="0421112222",
    )
    assert dup2 is not None
    assert "電話" in dup2[1]


def test_import_skips_existing_and_adds_new(temp_store_db: StoreDatabase, tmp_path):
    temp_store_db.add_store(
        {
            "store_name": "ハードオフ多摩和田店",
            "store_code": "HA-99",
            "phone": "042-111-2222",
            "address": "東京都多摩市和田1-1",
            "latitude": 35.63,
            "longitude": 139.45,
        }
    )
    csv_path = tmp_path / "fav.csv"
    csv_path.write_text(
        "タイトル,メモ,URL,タグ,コメント\n"
        "ハードオフ 多摩和田店,,https://x,,\n"
        "新規テスト店舗ABC,,https://y,,\n",
        encoding="utf-8-sig",
    )

    def fake_fetch(name: str):
        if "新規" in name:
            return {
                "address": "東京都新宿区1-2-3",
                "phone": "03-9999-8888",
                "latitude": 35.69,
                "longitude": 139.70,
            }
        return {
            "address": "東京都多摩市和田1-1",
            "phone": "042-111-2222",
            "latitude": 35.63,
            "longitude": 139.45,
        }

    result = import_takeout_favorites(
        temp_store_db,
        csv_path,
        fetch_info=fake_fetch,
        api_delay_sec=0,
    )
    assert len(result.skipped) >= 1
    assert len(result.added) == 1
    assert result.added[0].title == "新規テスト店舗ABC"
    added = temp_store_db.get_store(result.added[0].store_id)
    assert added is not None
    assert not (added.get("affiliated_route_name") or "").strip()
    assert added.get("address")
    assert added.get("phone")
