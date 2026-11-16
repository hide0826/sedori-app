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
    build_photo_candidate_rows,
    create_online_purchase_box,
    ensure_online_route_registration,
    ensure_photo_candidates_from_csvs,
    extract_record_box_ymd,
    format_box_date,
    group_records_by_box_ymd,
    load_photo_candidates,
    records_from_listing_export,
    records_from_purchase_csv,
    resolve_default_online_root,
    sanitize_folder_label,
    write_photo_candidates,
    write_photo_candidates_grouped_by_box,
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


def test_photo_candidate_keeps_condition_and_sku():
    rows = build_photo_candidate_rows(
        [
            {
                "SKU": "20261017-14200-OFM-6P-001",
                "JAN": "4571157325181",
                "商品名": "ワイヤレスヘッドホン",
                "コンディション": "中古(非常に良い)",
            }
        ]
    )
    assert rows[0]["sku"] == "20261017-14200-OFM-6P-001"
    assert rows[0]["condition"] == "中古(非常に良い)"
    assert rows[0]["jan"] == "4571157325181"


def test_extract_record_box_ymd_from_sku_and_date():
    assert extract_record_box_ymd({"SKU": "20261113-MERCARI-1000-6P-001"}) == "20261113"
    assert extract_record_box_ymd({"sku": "x", "仕入れ日": "2026-11-11"}) == "20261111"
    assert extract_record_box_ymd({"商品名": "only name"}) == ""


def test_group_and_write_photo_candidates_by_box(tmp_path: Path):
    route_registry.DATA_DIR = tmp_path  # type: ignore
    route_registry.INDEX_PATH = tmp_path / "index.json"  # type: ignore
    root = tmp_path / "ネット仕入れリスト"
    root.mkdir()
    written = write_photo_candidates_grouped_by_box(
        root,
        [
            {"SKU": "20261111-MERCARI-1", "ASIN": "B00AAAAAAA", "商品名": "11の商品"},
            {"SKU": "20261113-MERCARI-2", "ASIN": "B00BBBBBBB", "商品名": "13の商品"},
            {"SKU": "20261113-MERCARI-3", "JAN": "4901234567890", "商品名": "13の別商品"},
        ],
        label="フリマ",
        register_web=True,
    )
    names = {path.name: len(rows) for path, rows, _ymd in written}
    assert names["フリマ20261111"] == 1
    assert names["フリマ20261113"] == 2
    assert (root / "フリマ20261111" / PHOTO_CANDIDATES_FILE).is_file()
    assert len(load_photo_candidates(root / "フリマ20261113")) == 2


def test_records_from_listing_export(tmp_path: Path):
    path = tmp_path / "listing_export.csv"
    path.write_text(
        "\n".join(
            [
                '"ASINかJANのどちらかを記載してください。","","",""',
                "SKU,ASIN,JAN,title,condition,conditionNote",
                '20261111-MERCARI-1,="B00TESTASIN",,テスト商品,3,[動作確認]OK',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rows = records_from_listing_export(path)
    assert len(rows) == 1
    assert rows[0]["SKU"] == "20261111-MERCARI-1"
    assert rows[0]["ASIN"] == "B00TESTASIN"
    assert rows[0]["商品名"] == "テスト商品"
    assert group_records_by_box_ymd(rows)["20261111"]


def test_records_from_listing_export_cp932(tmp_path: Path):
    path = tmp_path / "listing_export.csv"
    path.write_bytes(
        (
            "SKU,ASIN,JAN,title,condition,conditionNote\r\n"
            '20261113-MERCARI-1,="B00TESTASIN",,パナソニック 電話機,3,[動作確認]動作確認済みです。長い説明\r\n'
        ).encode("cp932")
    )
    rows = records_from_listing_export(path)
    assert len(rows) == 1
    assert "パナソニック" in rows[0]["商品名"]
    assert rows[0]["コンディション"] == "中古(良い)"
    assert "動作確認" not in rows[0]["コンディション"]


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


def test_records_from_amasearch_purchase_csv_assigns_tmp_sku(tmp_path: Path):
    path = tmp_path / "仕入れ済み商品一覧_20261114_standard.csv"
    path.write_bytes(
        (
            "仕入れ日,コンディション,ASIN,JAN,商品名,仕入れ個数,仕入れ価格,SKU\r\n"
            "2026/11/9 6:59,中古(非常に良い),B0B12JPQ6Y,4981747075680,コイズミ ドライヤー,1,2760,\r\n"
            "2026/11/12 12:30,中古(良い),B00CTJLIYC,4902704218995,パナソニック 電話機,1,3999,\r\n"
        ).encode("cp932")
    )
    rows = records_from_purchase_csv(path, fallback_ymd="20261114")
    assert len(rows) == 2
    assert rows[0]["SKU"].startswith("TMP-")
    assert rows[0]["ASIN"] == "B0B12JPQ6Y"
    assert "コイズミ" in rows[0]["商品名"]
    assert rows[0]["コンディション"] == "中古(非常に良い)"
    assert rows[1]["コンディション"] == "中古(良い)"


def test_ensure_photo_candidates_from_shiire_csv(tmp_path: Path):
    route_registry.DATA_DIR = tmp_path  # type: ignore
    route_registry.INDEX_PATH = tmp_path / "index.json"  # type: ignore

    box = tmp_path / "フリマ20261114"
    box.mkdir()
    (box / CSV_DIR_NAME).mkdir()
    csv_path = box / CSV_DIR_NAME / "仕入れ済み商品一覧_20261114.csv"
    csv_path.write_text(
        "\n".join(
            [
                "仕入れ日,コンディション,ASIN,JAN,商品名,SKU",
                "2026/11/14,中古(良い),B00TESTASIN,4901234567890,テスト商品,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ensure_online_route_registration(box, box_date="20261114", route_name=box.name)
    result = ensure_photo_candidates_from_csvs(box, register_web=False)
    assert result is not None
    _path, rows = result
    assert len(rows) == 1
    assert rows[0]["asin"] == "B00TESTASIN"
    assert rows[0]["sku"].startswith("TMP-")
    assert (box / PHOTO_CANDIDATES_FILE).is_file()

    # 候補の方が新しいときは上書きしない
    older = box / CSV_DIR_NAME / "古い.csv"
    older.write_text(
        "仕入れ日,コンディション,ASIN,JAN,商品名,SKU\n2026/11/14,中古(可),B00OLDASIN,,古いだけ,\n",
        encoding="utf-8",
    )
    import os
    import time

    cand = box / PHOTO_CANDIDATES_FILE
    now = time.time()
    os.utime(cand, (now + 10, now + 10))
    os.utime(older, (now - 10, now - 10))
    os.utime(csv_path, (now - 10, now - 10))
    again = ensure_photo_candidates_from_csvs(box, register_web=False)
    assert again is not None
    assert again[1][0]["asin"] == "B00TESTASIN"


def test_ensure_photo_candidates_merges_multiple_csvs(tmp_path: Path):
    route_registry.DATA_DIR = tmp_path  # type: ignore
    route_registry.INDEX_PATH = tmp_path / "index.json"  # type: ignore

    box = tmp_path / "フリマ20261115"
    box.mkdir()
    (box / CSV_DIR_NAME).mkdir()
    (box / CSV_DIR_NAME / "a.csv").write_text(
        "仕入れ日,コンディション,ASIN,JAN,商品名,SKU\n"
        "2026/11/15,中古(良い),B00AAAAAAA,4901111111111,商品A,\n",
        encoding="utf-8",
    )
    (box / CSV_DIR_NAME / "b.csv").write_text(
        "仕入れ日,コンディション,ASIN,JAN,商品名,SKU\n"
        "2026/11/15,中古(可),B00BBBBBBB,4902222222222,商品B,\n",
        encoding="utf-8",
    )
    # 同じASINは出品CSVの本SKUに寄せる
    (box / "20261115_出品用CSV.csv").write_text(
        "\n".join(
            [
                "SKU,ASIN,JAN,title,condition",
                '20261115-MERCARI-1,="B00AAAAAAA",,商品A正式,3',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ensure_online_route_registration(box, box_date="20261115", route_name=box.name)
    result = ensure_photo_candidates_from_csvs(box, force=True, register_web=False)
    assert result is not None
    rows = result[1]
    asins = {row["asin"] for row in rows}
    assert asins == {"B00AAAAAAA", "B00BBBBBBB"}
    by_asin = {row["asin"]: row for row in rows}
    assert by_asin["B00AAAAAAA"]["sku"] == "20261115-MERCARI-1"
    assert by_asin["B00BBBBBBB"]["sku"].startswith("TMP-")
    assert len(rows) == 2


def test_write_photo_candidates_remaps_tmp_sku_files(tmp_path: Path):
    """仮SKUで撮った画像が、本SKU候補書き込み時にファイル名ごと付け替わる。"""
    route_registry.DATA_DIR = tmp_path  # type: ignore
    route_registry.INDEX_PATH = tmp_path / "index.json"  # type: ignore

    box = tmp_path / "フリマ20261116"
    box.mkdir()
    ensure_online_route_registration(box, box_date="20261116", route_name=box.name)
    raw = b"\xff\xd8\xff\xd9"
    tmp_sku = "TMP-20261116-001"
    fn = save_product_upload(
        box, "2026-11-16", ONLINE_ROUTE_CODE, raw, sku=tmp_sku
    )
    route_path = box / "route.json"
    doc = json.loads(route_path.read_text(encoding="utf-8"))
    doc["product_files"] = [{"file": fn, "sku": tmp_sku, "asin": "B00CCCCCCC"}]
    doc["photo_candidates"] = [
        {"sku": tmp_sku, "asin": "B00CCCCCCC", "jan": "", "product_name": "仮"}
    ]
    route_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (box / PHOTO_CANDIDATES_FILE).write_text(
        json.dumps({"candidates": doc["photo_candidates"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    real = "20261116-MERCARI-6P-009"
    write_photo_candidates(
        box,
        [
            {
                "SKU": real,
                "ASIN": "B00CCCCCCC",
                "JAN": "",
                "商品名": "本SKU商品",
            }
        ],
        route_date="2026-11-16",
        route_name=box.name,
    )
    assert (box / PRODUCT_DIR_NAME / f"{real}_1.jpg").is_file()
    assert not (box / PRODUCT_DIR_NAME / fn).exists()
    updated = json.loads(route_path.read_text(encoding="utf-8"))
    assert updated["product_files"][0]["file"] == f"{real}_1.jpg"
    assert updated["product_files"][0]["sku"] == real
    assert updated["photo_candidates"][0]["sku"] == real
