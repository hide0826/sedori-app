# -*- coding: utf-8 -*-
"""Phase 2 / 5 route_web helpers."""

from __future__ import annotations

import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

DESKTOP_DIR = PYTHON_DIR / "desktop"
if str(DESKTOP_DIR) not in sys.path:
    sys.path.insert(0, str(DESKTOP_DIR))

from route_web import csv_inbox
from route_web.product_images import append_product_file, next_product_filename, save_product_upload
from route_web.schema import build_route_document
from services.route_folder_import import find_stocklist_csv, resolve_route_folder_layout


def test_csv_inbox_move_and_upload(tmp_path: Path, monkeypatch=None):
    inbox = tmp_path / "仕入CSV_受信"
    inbox.mkdir()
    route = tmp_path / "20260922test"
    route.mkdir()
    (route / "仕入CSV").mkdir()

    # monkeypatch inbox_dir
    csv_inbox.LEDGER_PARENT = tmp_path  # type: ignore
    src = inbox / "StockList_demo.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    name = csv_inbox.move_from_inbox(route, "StockList_demo.csv")
    assert name == "StockList_demo.csv"
    assert (route / "仕入CSV" / name).is_file()
    assert not src.exists()

    saved = csv_inbox.save_csv_upload(route, b"x,y\n", original_name="StockList_up.csv")
    assert saved.endswith(".csv")
    assert (route / "仕入CSV" / saved).is_file()


def test_find_stocklist_prefers_subdir(tmp_path: Path):
    root = tmp_path / "box"
    root.mkdir(parents=True)
    sub = root / "仕入CSV"
    sub.mkdir()
    old = root / "StockList_old.csv"
    old.write_text("old", encoding="utf-8")
    new = sub / "StockList_new.csv"
    new.write_text("new", encoding="utf-8")
    found = find_stocklist_csv(root)
    assert found is not None
    assert found.name == "StockList_new.csv"


def test_product_upload_and_jan(tmp_path: Path):
    folder = tmp_path / "route"
    folder.mkdir(parents=True)
    # minimal jpeg-ish bytes; save may keep raw if PIL fails decode
    raw = b"\xff\xd8\xff\xd9"
    fn = save_product_upload(folder, "2026-09-22", "HA-01", raw, original_name="x.jpg")
    assert fn.startswith("2026-09-22-HA-01-item-")
    assert (folder / "商品画像" / fn).is_file()
    fn2 = next_product_filename(folder, "2026-09-22", "HA-01")
    assert fn2.endswith("02.jpg") or "item-02" in fn2

    doc = build_route_document(
        web_id="t",
        folder_path=str(folder),
        route_date="2026-09-22",
        route_code="R",
        route_name="n",
        stores=[{"visit_order": 1, "store_code": "HA-01", "store_name": "H"}],
    )
    doc = append_product_file(doc, "HA-01", fn, jan="4901234567890")
    files = doc["stores"][0]["product_files"]
    assert files[0]["file"] == fn
    assert files[0]["jan"] == "4901234567890"


def test_resolve_layout(tmp_path: Path):
    root = tmp_path / "box"
    (root / "仕入CSV").mkdir(parents=True)
    (root / "商品画像").mkdir()
    (root / "レシート画像").mkdir()
    (root / "仕入CSV" / "StockList_x.csv").write_text("a", encoding="utf-8")
    layout = resolve_route_folder_layout(root)
    assert layout.csv_path is not None
    assert layout.product_dir is not None
    assert layout.receipt_dir is not None


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        test_csv_inbox_move_and_upload(p)
        test_find_stocklist_prefers_subdir(p / "a")
        test_product_upload_and_jan(p / "b")
        test_resolve_layout(p / "c")
    print("ok route_web phase2/3/5 helpers")
