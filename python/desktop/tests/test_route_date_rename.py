# -*- coding: utf-8 -*-
"""ルート日付を変えたとき、箱と中のファイル名が付いてくるか。"""

from __future__ import annotations

import json
from pathlib import Path

from route_web.date_rename import change_route_date, parse_route_date
from route_web.registry import load_index, register_route
import route_web.registry as registry


def test_parse_route_date_accepts_compact_form():
    assert parse_route_date("2026/10/17") == "2026-10-17"
    assert parse_route_date("20261017") == "2026-10-17"


def test_change_route_date_renames_box_files_and_insurance(tmp_path: Path):
    registry.DATA_DIR = tmp_path / "webdata"
    registry.INDEX_PATH = registry.DATA_DIR / "index.json"

    box = tmp_path / "仕入帳" / "20261016千葉幕張習志野ルート"
    (box / "レシート画像").mkdir(parents=True)
    (box / "商品画像").mkdir()
    (box / "仕入CSV").mkdir()
    receipt = box / "レシート画像" / "2026-10-16-BO-12-01.jpg"
    product = box / "商品画像" / "2026-10-16-R046-item-01.jpg"
    csv_path = box / "仕入CSV" / "StockList_20261016.csv"
    excel = box / "route_template_千葉幕張習志野ルート_20261016.xlsx"
    prep = box / "prep_status.json"
    receipt.write_bytes(b"r")
    product.write_bytes(b"p")
    csv_path.write_text("a\n", encoding="utf-8")
    excel.write_bytes(b"not-a-real-xlsx")
    prep.write_text(
        json.dumps({"csv_name": "StockList_20261016.csv", "file": "2026-10-16-BO-12-01.jpg"}),
        encoding="utf-8",
    )

    insurance_root = tmp_path / "ルート保険"
    insurance = insurance_root / box.name
    insurance.mkdir(parents=True)
    (insurance / excel.name).write_bytes(b"copy")

    web_id = "20261016_千葉幕張習志野ルート"
    register_route(web_id, str(box), route_name="千葉幕張習志野ルート", route_date="2026-10-16")
    doc = {
        "web_id": web_id,
        "folder_path": str(box),
        "route_date": "2026-10-16",
        "route_name": "千葉幕張習志野ルート",
        "stores": [
            {
                "store_code": "BO-12",
                "receipt_files": ["2026-10-16-BO-12-01.jpg"],
                "product_files": [{"file": "2026-10-16-R046-item-01.jpg", "jan": "4571157325181"}],
            }
        ],
    }

    updated = change_route_date(
        box,
        doc,
        "2026-10-16",
        "2026-10-17",
        insurance_root=insurance_root,
    )

    new_box = tmp_path / "仕入帳" / "20261017千葉幕張習志野ルート"
    assert new_box.is_dir()
    assert not box.exists()
    assert (new_box / "レシート画像" / "2026-10-17-BO-12-01.jpg").is_file()
    assert (new_box / "商品画像" / "2026-10-17-R046-item-01.jpg").is_file()
    assert (new_box / "仕入CSV" / "StockList_20261017.csv").is_file()
    assert (new_box / "route_template_千葉幕張習志野ルート_20261017.xlsx").is_file()
    prep_doc = json.loads((new_box / "prep_status.json").read_text(encoding="utf-8"))
    assert prep_doc["csv_name"] == "StockList_20261017.csv"
    assert prep_doc["file"] == "2026-10-17-BO-12-01.jpg"
    assert updated["route_date"] == "2026-10-17"
    assert updated["folder_path"] == str(new_box)
    assert updated["stores"][0]["receipt_files"] == ["2026-10-17-BO-12-01.jpg"]
    assert updated["stores"][0]["product_files"][0]["file"] == "2026-10-17-R046-item-01.jpg"
    assert updated["stores"][0]["product_files"][0]["jan"] == "4571157325181"
    new_insurance = insurance_root / "20261017千葉幕張習志野ルート"
    assert new_insurance.is_dir()
    assert (new_insurance / "route_template_千葉幕張習志野ルート_20261017.xlsx").is_file()
    indexed = load_index()["routes"][web_id]
    assert indexed["folder_path"] == str(new_box)
    assert indexed["route_date"] == "2026-10-17"
