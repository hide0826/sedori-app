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
    import_takeout_places,
    normalize_address,
    normalize_phone,
    normalize_store_name,
    parse_store_names_text,
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


def test_import_collocated_hardoff_inherits_route(temp_store_db: StoreDatabase, tmp_path):
    temp_store_db.upsert_route("青葉ルート", "A1")
    temp_store_db.add_store(
        {
            "store_name": "ハードオフ横浜青葉店",
            "store_code": "HA-10",
            "affiliated_route_name": "青葉ルート",
            "route_code": "A1",
            "latitude": 35.5520,
            "longitude": 139.5410,
        }
    )
    csv_path = tmp_path / "colloc.csv"
    csv_path.write_text(
        "タイトル,メモ,URL,タグ,コメント\n"
        "ホビーオフ横浜青葉店,,https://x,,\n"
        "オフハウス横浜青葉店,,https://y,,\n",
        encoding="utf-8-sig",
    )

    def fake_fetch(name: str):
        # 既存ハードオフから十数m以内
        if "ホビー" in name:
            return {
                "address": "横浜市青葉区1",
                "phone": "045-111-2222",
                "latitude": 35.55205,
                "longitude": 139.54105,
            }
        return {
            "address": "横浜市青葉区2",
            "phone": "045-111-3333",
            "latitude": 35.55210,
            "longitude": 139.54110,
        }

    result = import_takeout_favorites(
        temp_store_db,
        csv_path,
        fetch_info=fake_fetch,
        api_delay_sec=0,
    )
    assert len(result.added) == 2
    for row in result.added:
        store = temp_store_db.get_store(row.store_id)
        assert store is not None
        assert store.get("affiliated_route_name") == "青葉ルート"
        assert store.get("route_code") == "A1"
        assert row.route_name == "青葉ルート"
        # 既存HA、または先に取り込まれた併設HOのどちらかを参照する
        assert row.collocated_with
        assert any(
            key in row.collocated_with for key in ("ハードオフ", "ホビーオフ")
        )


def test_parse_store_names_text_basic():
    text = """
BOOKOFF SUPER BAZAAR 多摩永山店
BOOKOFF SUPER BAZAAR 立川駅北口店

# コメント行
ハードオフ 八王子大和田店
ハードオフ 八王子大和田店
BOOKOFF PLUS 町田旭町店
"""
    rows = parse_store_names_text(text)
    assert [r.title for r in rows] == [
        "BOOKOFF SUPER BAZAAR 多摩永山店",
        "BOOKOFF SUPER BAZAAR 立川駅北口店",
        "ハードオフ 八王子大和田店",
        "BOOKOFF PLUS 町田旭町店",
    ]


def test_import_takeout_places_from_text(temp_store_db: StoreDatabase):
    places = parse_store_names_text(
        "既存テスト店XYZ\n新規テキスト店舗DEF\n"
    )
    temp_store_db.add_store(
        {
            "store_name": "既存テスト店XYZ",
            "store_code": "ZZ-01",
            "phone": "03-1111-2222",
            "address": "東京都千代田区1-1",
            "latitude": 35.68,
            "longitude": 139.76,
        }
    )

    def fake_fetch(name: str):
        if "新規" in name:
            return {
                "address": "東京都新宿区9-9-9",
                "phone": "03-7777-6666",
                "latitude": 35.69,
                "longitude": 139.70,
            }
        return {
            "address": "東京都千代田区1-1",
            "phone": "03-1111-2222",
            "latitude": 35.68,
            "longitude": 139.76,
        }

    result = import_takeout_places(
        temp_store_db,
        places,
        fetch_info=fake_fetch,
        api_delay_sec=0,
    )
    assert len(result.skipped) >= 1
    assert len(result.added) == 1
    assert result.added[0].title == "新規テキスト店舗DEF"


def test_hardoff_hobby_same_address_not_duplicate():
    """併設のホビーオフは住所・電話が同じでも別店舗として通す。"""
    existing = [
        {
            "id": 1,
            "store_name": "ハードオフ 埼玉東松山店",
            "store_code": "HA-99",
            "phone": "0493-27-1065",
            "address": "〒355-0017 埼玉県東松山市桜山町４丁目３－１８",
            "latitude": 36.04,
            "longitude": 139.40,
        }
    ]
    index = _DuplicateIndex(existing)
    # 店名だけなら未登録
    assert index.find_duplicate(title="ホビーオフ 埼玉東松山店") is None
    # 住所・電話・座標が同じでも別ブランド併設は通す
    dup = index.find_duplicate(
        title="ホビーオフ 埼玉東松山店",
        address="〒355-0017 埼玉県東松山市桜山町４丁目３－１８",
        phone="0493-27-1065",
        latitude=36.04,
        longitude=139.40,
    )
    assert dup is None

    # 同ブランドのゆれは重複
    dup_same = index.find_duplicate(
        title="ハードオフ埼玉東松山店",
        address="〒355-0017 埼玉県東松山市桜山町４丁目３－１８",
        phone="0493-27-1065",
    )
    assert dup_same is not None


def test_import_hardoff_and_hobby_same_site(temp_store_db: StoreDatabase):
    places = parse_store_names_text(
        "ハードオフ 高麗川店\nホビーオフ 高麗川店\n"
    )

    def fake_fetch(name: str):
        # 併設店は Google が同じ住所・電話・座標を返すことがある
        return {
            "address": "〒350-1231 埼玉県日高市鹿山３００－１",
            "phone": "042-978-7979",
            "latitude": 35.90,
            "longitude": 139.34,
        }

    result = import_takeout_places(
        temp_store_db,
        places,
        fetch_info=fake_fetch,
        api_delay_sec=0,
    )
    assert len(result.added) == 2, (result.added, result.skipped, result.failed)
    names = {row.title for row in result.added}
    assert "ハードオフ 高麗川店" in names
    assert "ホビーオフ 高麗川店" in names
    hobby = next(r for r in result.added if "ホビー" in r.title)
    hard = next(r for r in result.added if "ハード" in r.title)
    # チェーンマッピングがあれば HA/HO。無くても追加自体は成功していればよい
    if hard.store_code:
        assert hard.store_code.upper().startswith("HA")
    if hobby.store_code:
        assert hobby.store_code.upper().startswith("HO")
