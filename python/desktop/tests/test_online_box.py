# -*- coding: utf-8 -*-
"""ネット仕入箱作成の単体テスト。"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[1]
PYTHON_DIR = DESKTOP_DIR.parent
for p in (str(PYTHON_DIR), str(DESKTOP_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

from services.online_box import (
    CSV_DIR_NAME,
    EVIDENCE_DIR_NAME,
    ONLINE_BOX_KIND,
    ONLINE_ROUTE_CODE,
    PHOTO_CANDIDATES_FILE,
    PRODUCT_DIR_NAME,
    build_online_box_name,
    create_online_purchase_box,
    ensure_online_route_registration,
    format_box_date,
    load_photo_candidates,
    resolve_default_online_root,
    sanitize_folder_label,
    write_photo_candidates,
)
from route_web import registry as route_registry
from route_web.product_images import save_product_upload
from route_web.route_purchases import list_route_purchases


def test_sanitize_and_name():
    assert sanitize_folder_label("フリマ/A") == "フリマ_A"
    assert build_online_box_name("フリマ", date(2026, 10, 1)) == "フリマ20261001"
    assert format_box_date("2026-10-01") == "20261001"


def test_create_online_purchase_box(tmp_path: Path):
    root = tmp_path / "ネット仕入れリスト"
    root.mkdir()
    result = create_online_purchase_box(
        root, label="フリマ", box_date="20261001", register_web=False
    )
    assert result.created_box is True
    assert result.box_dir.name == "フリマ20261001"
    assert result.csv_dir.is_dir()
    assert result.product_dir.is_dir()
    assert result.evidence_dir.is_dir()
    assert result.csv_dir.name == CSV_DIR_NAME
    assert result.product_dir.name == PRODUCT_DIR_NAME
    assert result.evidence_dir.name == EVIDENCE_DIR_NAME
    assert set(result.created_subdirs) == {
        CSV_DIR_NAME,
        PRODUCT_DIR_NAME,
        EVIDENCE_DIR_NAME,
    }

    again = create_online_purchase_box(
        root, label="フリマ", box_date="20261001", register_web=False
    )
    assert again.created_box is False
    assert again.created_subdirs == []
    assert again.box_dir == result.box_dir


def test_create_fills_missing_subdir(tmp_path: Path):
    root = tmp_path / "parent"
    root.mkdir()
    box = root / "フリマ20261001"
    box.mkdir()
    (box / CSV_DIR_NAME).mkdir()
    result = create_online_purchase_box(
        root, label="フリマ", box_date=date(2026, 10, 1), register_web=False
    )
    assert result.created_box is False
    assert PRODUCT_DIR_NAME in result.created_subdirs
    assert EVIDENCE_DIR_NAME in result.created_subdirs
    assert CSV_DIR_NAME not in result.created_subdirs


def test_resolve_default_online_root(tmp_path: Path):
    base = tmp_path / "roots"
    base.mkdir()
    a = base / "ネット仕入れリスト"
    b = base / "ネット仕入リスト"
    assert resolve_default_online_root([a, b]) is None
    b.mkdir()
    assert resolve_default_online_root([a, b]) == b
    a.mkdir()
    assert resolve_default_online_root([a, b]) == a


def test_register_online_box_and_candidates(tmp_path: Path, monkeypatch=None):
    index_path = tmp_path / "index.json"
    route_registry.DATA_DIR = tmp_path  # type: ignore
    route_registry.INDEX_PATH = index_path  # type: ignore

    root = tmp_path / "ネット仕入れリスト"
    root.mkdir()
    result = create_online_purchase_box(
        root, label="フリマ", box_date="20261001", register_web=True
    )
    assert result.web_id
    assert result.route_json is not None and result.route_json.is_file()
    doc = json.loads(result.route_json.read_text(encoding="utf-8"))
    assert doc["box_kind"] == ONLINE_BOX_KIND
    assert doc["route_code"] == ONLINE_ROUTE_CODE
    assert doc["stores"] == []
    assert route_registry.resolve_folder(result.web_id) == result.box_dir

    path, rows = write_photo_candidates(
        result.box_dir,
        [
            {"SKU": "S1", "ASIN": "B00TESTASIN", "商品名": "テスト商品", "JAN": ""},
            {"sku": "S2", "jan": "4901234567890", "product_name": "JAN商品"},
        ],
        route_name=result.box_dir.name,
    )
    assert path.name == PHOTO_CANDIDATES_FILE
    assert len(rows) == 2
    loaded = load_photo_candidates(result.box_dir)
    assert len(loaded) == 2

    doc2 = json.loads((result.box_dir / "route.json").read_text(encoding="utf-8"))
    purchases = list_route_purchases(doc2)
    assert len(purchases) == 2
    assert purchases[0]["asin"] == "B00TESTASIN" or purchases[1]["asin"] == "B00TESTASIN"

    raw = b"\xff\xd8\xff\xd9"
    fn = save_product_upload(
        result.box_dir,
        "2026-10-01",
        ONLINE_ROUTE_CODE,
        raw,
        original_name="x.jpg",
    )
    assert (result.box_dir / PRODUCT_DIR_NAME / fn).is_file()
    assert "NET" in fn


def test_ensure_preserves_product_files(tmp_path: Path):
    route_registry.DATA_DIR = tmp_path  # type: ignore
    route_registry.INDEX_PATH = tmp_path / "index.json"  # type: ignore

    box = tmp_path / "フリマ20261001"
    box.mkdir()
    web_id, path = ensure_online_route_registration(box, box_date="20261001")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["product_files"] = [{"file": "a.jpg", "jan": "1", "confirmed": True}]
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    web_id2, path2 = ensure_online_route_registration(box, box_date="20261001")
    assert web_id2 == web_id
    again = json.loads(path2.read_text(encoding="utf-8"))
    assert again["product_files"][0]["file"] == "a.jpg"
    assert again["box_kind"] == ONLINE_BOX_KIND
