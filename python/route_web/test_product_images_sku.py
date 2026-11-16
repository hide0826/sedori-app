# -*- coding: utf-8 -*-
"""同JANの複数SKUが、撮影終了でまとめて消えないこと。SKUファイル名まわり。"""

from __future__ import annotations

from pathlib import Path

from route_web.product_images import (
    append_route_product_file,
    confirm_route_product_group,
    confirmed_product_groups,
    is_sku_indexed_product_filename,
    is_tmp_sku,
    mark_no_image,
    list_no_image_products,
    next_sku_product_filename,
    remap_product_files_sku,
    resolve_sku_for_product_upload,
    save_product_upload,
)


def test_confirm_one_sku_keeps_same_jan_other_sku() -> None:
    doc: dict = {"product_files": []}
    jan = "4901234567890"
    doc = append_route_product_file(doc, "a1.jpg", jan=jan, sku="20261026-BO-01-A-001")
    doc = append_route_product_file(doc, "a2.jpg", jan=jan, sku="20261026-BO-01-A-001")
    doc = append_route_product_file(doc, "b1.jpg", jan=jan, sku="20261026-BO-01-A-002")

    doc = confirm_route_product_group(
        doc,
        jan=jan,
        sku="20261026-BO-01-A-001",
    )
    groups = confirmed_product_groups(doc)
    assert len(groups) == 1
    assert groups[0]["sku"] == "20261026-BO-01-A-001"
    assert set(groups[0]["files"]) == {"a1.jpg", "a2.jpg"}

    remaining = [
        item
        for item in doc["product_files"]
        if not item.get("confirmed")
    ]
    assert len(remaining) == 1
    assert remaining[0]["file"] == "b1.jpg"
    assert remaining[0]["sku"] == "20261026-BO-01-A-002"


def test_no_image_is_per_sku() -> None:
    doc: dict = {}
    jan = "4901234567890"
    doc = mark_no_image(doc, jan=jan, sku="SKU-1")
    doc = mark_no_image(doc, jan=jan, sku="SKU-2")
    rows = list_no_image_products(doc)
    assert len(rows) == 2
    assert {row["sku"] for row in rows} == {"SKU-1", "SKU-2"}


def test_save_uses_sku_indexed_filename(tmp_path: Path) -> None:
    raw = b"\xff\xd8\xff\xd9"
    fn = save_product_upload(
        tmp_path,
        "2026-11-13",
        "NET",
        raw,
        original_name="x.jpg",
        sku="TMP-20261113-001",
    )
    assert fn == "TMP-20261113-001_1.jpg"
    assert (tmp_path / "商品画像" / fn).is_file()
    fn2 = save_product_upload(
        tmp_path,
        "2026-11-13",
        "NET",
        raw,
        original_name="y.jpg",
        sku="TMP-20261113-001",
    )
    assert fn2 == "TMP-20261113-001_2.jpg"
    assert next_sku_product_filename(tmp_path, "TMP-20261113-001") == "TMP-20261113-001_3.jpg"


def test_save_without_sku_keeps_legacy_item_name(tmp_path: Path) -> None:
    raw = b"\xff\xd8\xff\xd9"
    fn = save_product_upload(
        tmp_path,
        "2026-11-13",
        "NET",
        raw,
        original_name="x.jpg",
    )
    assert fn.startswith("2026-11-13-NET-item-")
    assert not is_sku_indexed_product_filename(fn)


def test_remap_tmp_to_real_sku(tmp_path: Path) -> None:
    raw = b"\xff\xd8\xff\xd9"
    fn1 = save_product_upload(
        tmp_path, "2026-11-13", "NET", raw, sku="TMP-20261113-001"
    )
    fn2 = save_product_upload(
        tmp_path, "2026-11-13", "NET", raw, sku="TMP-20261113-001"
    )
    doc = {"product_files": []}
    doc = append_route_product_file(doc, fn1, asin="B00AAAAAAA", sku="TMP-20261113-001")
    doc = append_route_product_file(doc, fn2, asin="B00AAAAAAA", sku="TMP-20261113-001")
    real = "20261113-MERCARI-6P-001"
    doc2, renamed = remap_product_files_sku(tmp_path, doc, "TMP-20261113-001", real)
    assert renamed == 2
    assert (tmp_path / "商品画像" / f"{real}_1.jpg").is_file()
    assert (tmp_path / "商品画像" / f"{real}_2.jpg").is_file()
    assert not (tmp_path / "商品画像" / fn1).exists()
    assert doc2["product_files"][0]["file"] == f"{real}_1.jpg"
    assert doc2["product_files"][0]["sku"] == real
    assert doc2["product_files"][1]["sku"] == real


def test_remap_rejects_real_to_tmp(tmp_path: Path) -> None:
    raw = b"\xff\xd8\xff\xd9"
    real = "20261113-MERCARI-6P-001"
    fn = save_product_upload(tmp_path, "2026-11-13", "NET", raw, sku=real)
    doc = append_route_product_file({"product_files": []}, fn, sku=real)
    doc2, renamed = remap_product_files_sku(tmp_path, doc, real, "TMP-20261113-001")
    assert renamed == 0
    assert (tmp_path / "商品画像" / fn).is_file()
    assert doc2["product_files"][0]["file"] == fn


def test_is_tmp_and_sku_indexed_helpers() -> None:
    assert is_tmp_sku("TMP-20261113-001")
    assert not is_tmp_sku("20261113-MERCARI-6P-001")
    assert is_sku_indexed_product_filename("TMP-20261113-001_1.jpg")
    assert is_sku_indexed_product_filename("20261113-MERCARI-6P-001_2.jpg")
    assert not is_sku_indexed_product_filename("2026-11-13-NET-item-01.jpg")


def test_resolve_sku_from_csv_candidates_without_client_sku() -> None:
    """仕入CSV候補だけで撮るとき、SKU未送信でも仮SKU／候補SKUになる。"""
    doc = {
        "route_date": "2026-11-16",
        "photo_candidates": [
            {
                "sku": "TMP-20261116-001",
                "asin": "B00AAAAAAA",
                "jan": "",
                "product_name": "A",
            }
        ],
    }
    assert (
        resolve_sku_for_product_upload(
            doc, sku="", jan="", asin="B00AAAAAAA", route_date="2026-11-16"
        )
        == "TMP-20261116-001"
    )
    minted = resolve_sku_for_product_upload(
        {"route_date": "2026-11-16", "photo_candidates": []},
        sku="",
        jan="",
        asin="B00BBBBBBB",
        route_date="2026-11-16",
    )
    assert minted.startswith("TMP-20261116-")
    assert is_tmp_sku(minted)


def test_csv_candidate_upload_never_uses_item_filename(tmp_path: Path) -> None:
    raw = b"\xff\xd8\xff\xd9"
    doc = {
        "route_date": "2026-11-16",
        "photo_candidates": [
            {"sku": "TMP-20261116-XYZ", "asin": "B00CCCCCCC", "jan": ""}
        ],
    }
    sku = resolve_sku_for_product_upload(
        doc, sku="", asin="B00CCCCCCC", route_date="2026-11-16"
    )
    fn = save_product_upload(
        tmp_path, "2026-11-16", "NET", raw, sku=sku
    )
    assert fn.startswith("TMP-")
    assert "_1.jpg" in fn
    assert "item-" not in fn


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    test_confirm_one_sku_keeps_same_jan_other_sku()
    test_no_image_is_per_sku()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_save_uses_sku_indexed_filename(root / "a")
        test_save_without_sku_keeps_legacy_item_name(root / "b")
        test_remap_tmp_to_real_sku(root / "c")
        test_remap_rejects_real_to_tmp(root / "d")
        test_csv_candidate_upload_never_uses_item_filename(root / "e")
    test_is_tmp_and_sku_indexed_helpers()
    test_resolve_sku_from_csv_candidates_without_client_sku()
    print("ok")
