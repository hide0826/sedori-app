# -*- coding: utf-8 -*-
"""ルート先読み・撮影分離の関数テストとサンドボックス確認。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parents[2]
DESKTOP_DIR = PYTHON_DIR / "desktop"
for path in (str(PYTHON_DIR), str(DESKTOP_DIR)):
    if path in sys.path:
        sys.path.remove(path)
sys.path.insert(0, str(PYTHON_DIR))
sys.path.insert(0, str(DESKTOP_DIR))

from database.image_db import ImageDatabase
from database.product_db import ProductDatabase
from database.purchase_db import PurchaseDatabase
from route_web.prepare import prepare_route_folder
from route_web.product_images import append_product_file, confirm_product_group
from route_web.route_purchases import list_route_purchases
from route_web.scan_requests import enqueue_scan, peek_scans
from route_web.schema import build_route_document
from services.image_service import ImageRecord, ImageService
from services.route_folder_import import (
    RouteFolderLayout,
    choose_route_time_source,
    load_route_json_model,
)
from services.route_product_seed import consume_one_scan_request, seed_confirmed_jans

REAL_ROUTE = Path(r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20260919鎌倉ルート")
SANDBOX = Path(r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20260919鎌倉ルートサンドボックス")


def test_json_wins_over_xlsx(tmp: Path) -> None:
    folder = tmp / "box"
    folder.mkdir(parents=True)
    (folder / "route.json").write_text(
        json.dumps(
            {"stores": [{"store_code": "BO-04", "in_time": "10:06", "out_time": "11:00"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (folder / "route_template_demo.xlsx").write_bytes(b"not-a-real-xlsx")
    layout = RouteFolderLayout(
        root=folder,
        route_template=folder / "route_template_demo.xlsx",
        route_json=folder / "route.json",
    )
    assert choose_route_time_source(layout) == "json"
    layout.route_json = None
    assert choose_route_time_source(layout) == "xlsx"


def test_empty_json_falls_back_to_xlsx(tmp: Path) -> None:
    folder = tmp / "box"
    folder.mkdir(parents=True)
    (folder / "route.json").write_text("{}", encoding="utf-8")
    (folder / "route_template_demo.xlsx").write_bytes(b"not-a-real-xlsx")
    layout = RouteFolderLayout(
        root=folder,
        route_template=folder / "route_template_demo.xlsx",
        route_json=folder / "route.json",
    )
    assert choose_route_time_source(layout) == "xlsx"
    (folder / "route.json").write_text(
        json.dumps({"stores": [{"store_code": "BO-04", "store_name": "ブックオフ"}]}),
        encoding="utf-8",
    )
    assert choose_route_time_source(layout) == "xlsx"
    layout.route_template = None
    assert choose_route_time_source(layout) == "none"


def test_route_json_model(tmp: Path) -> None:
    path = tmp / "route.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "route_date": "2026-09-19",
                "route_name": "鎌倉",
                "route_code": "SANDBOX",
                "departure_time": "09:20",
                "return_time": "19:30",
                "toll_outbound": "830",
                "toll_return": "1080",
                "stores": [
                    {
                        "order": 1,
                        "store_code": "BO-04",
                        "store_name": "ブックオフ",
                        "in_time": "10:06",
                        "out_time": "11:23",
                        "notes": "メモ",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    model = load_route_json_model(path)
    assert model["source"] == "json"
    assert model["departure_time"] == "2026-09-19 09:20:00"
    assert model["toll_fee_outbound"] == 830
    assert model["visits"][0]["store_code"] == "BO-04"
    assert model["visits"][0]["in_time"] == "10:06"


def test_prepare_does_not_rename_and_skips_second_time(tmp: Path) -> None:
    folder = tmp / "route"
    receipt_dir = folder / "レシート画像"
    receipt_dir.mkdir(parents=True)
    (folder / "仕入CSV").mkdir()
    csv_path = folder / "仕入CSV" / "StockList_demo.csv"
    csv_path.write_text("a\n1\n", encoding="utf-8")
    image = receipt_dir / "2026-09-19-BO-04-01.jpg"
    image.write_bytes(b"fake-image")
    calls = {"n": 0}

    def fake_parse(path: Path):
        calls["n"] += 1
        assert path.name == image.name
        return {
            "purchase_date": "2026-09-19",
            "purchase_time": "10:10",
            "store_name_raw": "BOOKOFF",
            "phone_number": "",
            "subtotal": 1000,
            "tax": 100,
            "discount_amount": 0,
            "total_amount": 1100,
            "paid_amount": 1100,
            "items_count": 1,
            "plastic_bag_amount": 0,
            "ocr_provider": "test",
            "ocr_text": "TOTAL 1100",
            "registration_number": None,
        }

    db_path = str(tmp / "hirio.db")
    first = prepare_route_folder(folder, db_path=db_path, parse_fn=fake_parse)
    assert first["csv_present"] is True
    assert first["receipts"][0]["skipped"] is False
    assert image.read_bytes() == b"fake-image"
    second = prepare_route_folder(folder, db_path=db_path, parse_fn=fake_parse)
    assert second["receipts"][0]["skipped"] is True
    assert calls["n"] == 1


def test_confirm_and_scan_skips_barcode(tmp: Path) -> None:
    folder = tmp / "route"
    product_dir = folder / "商品画像"
    product_dir.mkdir(parents=True)
    from PIL import Image

    image_path = product_dir / "2026-09-19-BO-04-item-01.jpg"
    Image.new("RGB", (40, 40), (255, 255, 255)).save(image_path, format="JPEG")
    doc = build_route_document(
        web_id="t",
        folder_path=str(folder),
        route_date="2026-09-19",
        route_code="R",
        route_name="n",
        stores=[{"visit_order": 1, "store_code": "BO-04", "store_name": "B"}],
    )
    doc = append_product_file(doc, "BO-04", image_path.name, jan="4901234567890")
    doc = confirm_product_group(doc, "BO-04", "4901234567890")
    assert doc["stores"][0]["product_files"][0]["confirmed"] is True
    (folder / "route.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    db = ImageDatabase(str(tmp / "images.db"))
    seeded = seed_confirmed_jans(folder, db=db)
    assert seeded == 1
    stored = db.get_by_file_path(str(image_path))
    assert stored["jan"] == "4901234567890"

    service = ImageService()
    called = {"n": 0}

    def _forbid(*_args, **_kwargs):
        called["n"] += 1
        return None

    service.read_barcode_from_image = _forbid  # type: ignore
    record = ImageRecord(
        path=str(image_path),
        capture_dt=None,
        jan_candidate="4901234567890",
        width=0,
        height=0,
    )
    records = service.scan_directory(
        str(product_dir),
        skip_barcode_reading=False,
        skip_exif=True,
        skip_image_size=True,
        file_cache={str(image_path): {"record": record}},
    )
    assert called["n"] == 0
    assert records[0].jan_candidate == "4901234567890"

    pending = tmp / "pending_scans.json"
    enqueue_scan("t", folder, path=pending)

    class _Widget:
        def __init__(self):
            self.calls = []

        def set_directory(self, directory: str, *, scan: bool = False) -> bool:
            self.calls.append((directory, scan))
            return True

    widget = _Widget()
    result = consume_one_scan_request(widget, pending_path=pending, db=db)
    assert result is not None, result
    assert result.get("error") == "", result
    assert result["scanned"] is True
    assert widget.calls[0][1] is True
    assert peek_scans(pending) == []
    db.close()


def test_purchases_filter_without_writing_real_db(tmp: Path) -> None:
    db_path = str(tmp / "purchases.db")
    products = ProductDatabase(db_path)
    purchases = PurchaseDatabase(db_path)
    products.upsert(
        {
            "sku": "SKU-TEST",
            "jan": "4901234567890",
            "product_name": "テスト商品",
            "purchase_date": "2026-09-19",
            "store_code": "BO-04",
            "store_name": "ブックオフ",
        }
    )
    purchases.upsert(
        {
            "sku": "SKU-TEST",
            "purchase_date": "2026/09/19 10:30",
            "store_code": "BO-04",
            "store_name": "ブックオフ",
        }
    )
    doc = {
        "route_date": "2026-09-19",
        "stores": [{"store_code": "BO-04"}, {"store_code": "HA-07"}],
    }
    rows = list_route_purchases(doc, db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["jan"] == "4901234567890"
    assert rows[0]["product_name"] == "テスト商品"
    products.close()
    purchases.close()


def test_tour_page_hides_product_capture() -> None:
    html = (PYTHON_DIR / "route_web" / "static" / "route.html").read_text(encoding="utf-8")
    photos = (PYTHON_DIR / "route_web" / "static" / "route_photos.html").read_text(encoding="utf-8")
    assert "商品を撮る" not in html
    assert "事前処理を実行" in html
    assert "JANあり" in photos
    assert "撮影終了" in photos
    assert "スキャン実行" in photos


def _copy_if_missing(src: Path, dest: Path) -> bool:
    if not src.is_file() or dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def supplement_and_check_sandbox() -> None:
    """本番鎌倉ルートはコピー元だけ。書き込みはサンドボックスと、そのレシートOCR行だけ。"""
    if not SANDBOX.is_dir() or not REAL_ROUTE.is_dir():
        print("skip sandbox: folders missing")
        return
    real_before = sorted(str(p.relative_to(REAL_ROUTE)) for p in REAL_ROUTE.rglob("*"))

    csv_src = REAL_ROUTE / "StockList_20260919_2123_standard.csv"
    _copy_if_missing(csv_src, SANDBOX / "仕入CSV" / csv_src.name)
    xlsx = next(REAL_ROUTE.glob("route_template_*.xlsx"), None)
    if xlsx is not None:
        _copy_if_missing(xlsx, SANDBOX / xlsx.name)

    from services.route_folder_import import resolve_route_folder_layout

    layout = resolve_route_folder_layout(SANDBOX)
    assert choose_route_time_source(layout) == "json"
    model = load_route_json_model(layout.route_json)
    assert model["departure_time"].startswith("2026-09-19")
    assert model["visits"]

    product_src = sorted(
        p for p in (REAL_ROUTE / "商品画像").iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )[:2]
    copied = []
    for src in product_src:
        dest = SANDBOX / "商品画像" / src.name
        if _copy_if_missing(src, dest):
            copied.append(dest.name)
        elif dest.is_file():
            copied.append(dest.name)
    assert copied, "商品画像のコピーがありません"

    doc = json.loads((SANDBOX / "route.json").read_text(encoding="utf-8"))
    doc = append_product_file(doc, "BO-04", copied[0], jan="4901999000001")
    doc = confirm_product_group(doc, "BO-04", "4901999000001")
    (SANDBOX / "route.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    seeded = seed_confirmed_jans(SANDBOX)
    assert seeded >= 1

    receipt_dir = SANDBOX / "レシート画像"
    names = sorted(
        p.name for p in receipt_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )[:2]
    assert names
    before_names = {p.name for p in receipt_dir.iterdir()}
    status = prepare_route_folder(SANDBOX, only_files=names)
    after_names = {p.name for p in receipt_dir.iterdir() if p.suffix.lower() == ".jpg"}
    assert before_names >= after_names or before_names == {p.name for p in receipt_dir.iterdir()}
    for name in names:
        assert (receipt_dir / name).is_file()
    assert status["status"] == "done"
    assert status["csv_present"] is True
    again = prepare_route_folder(SANDBOX, only_files=names)
    assert all(row["skipped"] for row in again["receipts"])

    rows = list_route_purchases(doc)
    print(f"sandbox purchases matched: {len(rows)}")

    real_after = sorted(str(p.relative_to(REAL_ROUTE)) for p in REAL_ROUTE.rglob("*"))
    assert real_before == real_after
    print("sandbox ok", {"csv": status.get("csv_name"), "receipts": names, "seeded": seeded, "products": copied[:1]})


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="hirio_route_prep_") as raw:
        tmp = Path(raw)
        test_json_wins_over_xlsx(tmp / "src")
        test_empty_json_falls_back_to_xlsx(tmp / "fallback")
        test_route_json_model(tmp / "model")
        test_prepare_does_not_rename_and_skips_second_time(tmp / "prep")
        test_confirm_and_scan_skips_barcode(tmp / "scan")
        test_purchases_filter_without_writing_real_db(tmp / "buy")
    test_tour_page_hides_product_capture()
    print("unit ok")
    supplement_and_check_sandbox()


if __name__ == "__main__":
    main()
