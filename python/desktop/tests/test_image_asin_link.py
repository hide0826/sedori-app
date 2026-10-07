#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像管理の ASIN 紐付け（JAN無し）の単体テスト。"""
from __future__ import annotations

from pathlib import Path

from desktop.database.image_db import ImageDatabase
from desktop.services.route_product_seed import seed_linked_jans
from desktop.ui.image_manager.support import (
    _asin_group_key,
    _format_group_key_label,
    _group_key_from_db_fields,
    _normalize_asin_for_match,
    _parse_image_group_key,
    _record_jan_matches_group,
)
from desktop.ui.product.purchase_edit_mixin import PurchaseEditMixin


def test_parse_and_format_asin_group_key():
    assert _asin_group_key("b08xyz1234") == "asin:B08XYZ1234"
    assert _parse_image_group_key("asin:B08XYZ1234") == (None, "B08XYZ1234")
    assert _parse_image_group_key("4901234567890") == ("4901234567890", None)
    assert _parse_image_group_key("unknown") == (None, None)
    assert _format_group_key_label("asin:B08XYZ1234") == "ASIN: B08XYZ1234"
    assert _format_group_key_label("unknown") == "（JAN不明）"
    assert _group_key_from_db_fields(jan="", asin="B08XYZ1234") == "asin:B08XYZ1234"
    assert _group_key_from_db_fields(jan="4901234567890", asin="B08XYZ1234") == "4901234567890"


def test_record_matches_asin_group():
    rec = {"ASIN": "B08XYZ1234", "JAN": "", "商品名": "テスト"}
    assert _record_jan_matches_group(rec, "asin:B08XYZ1234") is True
    assert _record_jan_matches_group(rec, "4901234567890") is False


def test_update_image_paths_by_asin_without_jan(tmp_path: Path):
    """JAN が空でも ASIN で仕入レコードへ画像を書ける。"""

    class _Stub(PurchaseEditMixin):
        pass

    stub = _Stub()
    records = [
        {
            "SKU": "SKU-ASIN-1",
            "JAN": "",
            "ASIN": "B08XYZ1234",
            "商品名": "JAN無し商品",
            "画像1": "",
            "画像2": "",
            "画像3": "",
            "画像4": "",
            "画像5": "",
            "画像6": "",
        }
    ]
    img = str(tmp_path / "photo.jpg")
    ok, added, snap = stub.update_image_paths_for_jan(
        "",
        [img],
        records,
        skip_existing=True,
        target_asin="B08XYZ1234",
        defer_table_refresh_and_snapshot=True,
    )
    assert ok is True
    assert added == 1
    assert records[0]["画像1"] == img
    assert snap is not None


def test_update_image_paths_by_sku_when_jan_empty(tmp_path: Path):
    class _Stub(PurchaseEditMixin):
        pass

    stub = _Stub()
    records = [
        {
            "SKU": "ONLY-SKU",
            "JAN": "",
            "ASIN": "",
            "画像1": "",
            "画像2": "",
            "画像3": "",
            "画像4": "",
            "画像5": "",
            "画像6": "",
        }
    ]
    img = str(tmp_path / "a.jpg")
    ok, added, _snap = stub.update_image_paths_for_jan(
        "",
        [img],
        records,
        target_sku="ONLY-SKU",
        defer_table_refresh_and_snapshot=True,
    )
    assert ok is True
    assert added == 1
    assert records[0]["画像1"] == img


def test_image_db_stores_asin(tmp_path: Path):
    db = ImageDatabase(str(tmp_path / "images.db"))
    path = str(tmp_path / "x.jpg")
    db.upsert({"file_path": path, "jan": None, "asin": "B08XYZ1234", "rotation": 0})
    row = db.get_by_file_path(path)
    assert row["asin"] == "B08XYZ1234"
    assert not row.get("jan")
    found = db.get_by_asin("B08XYZ1234")
    assert len(found) == 1
    db.close()


def test_seed_asin_only_photo(tmp_path: Path):
    from PIL import Image
    import json

    folder = tmp_path / "route"
    product_dir = folder / "商品画像"
    product_dir.mkdir(parents=True)
    image_path = product_dir / "2026-10-07-R001-item-01.jpg"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(image_path, format="JPEG")
    doc = {
        "product_files": [
            {"file": image_path.name, "jan": "", "asin": "B08XYZ1234", "confirmed": False}
        ]
    }
    (folder / "route.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    db = ImageDatabase(str(tmp_path / "images.db"))
    assert seed_linked_jans(folder, db=db) == 1
    stored = db.get_by_file_path(str(image_path))
    assert stored["asin"] == "B08XYZ1234"
    assert not stored.get("jan")
    db.close()


def test_normalize_asin():
    assert _normalize_asin_for_match("asin:b08xyz1234") == "B08XYZ1234"
    assert _normalize_asin_for_match(" B08-XYZ ") == "B08XYZ"
