#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SKU画像ファイル命名ヘルパーのテスト"""
from __future__ import annotations

from dataclasses import dataclass

from utils.amazon_image_naming import (
    build_sku_indexed_filename,
    extract_sku_from_image_path,
    extract_sku_from_image_stem,
    infer_sku_from_sorted_images,
    is_amazon_sku_filename,
    is_legacy_sku_filename,
    needs_amazon_sequence_rerename,
    plan_amazon_rename_targets,
    plan_amazon_rerename_targets,
    product_image_slots_from_sorted_images,
)


@dataclass
class _Img:
    path: str


SKU = "20260124-SS-22-027"


def test_build_filename():
    assert build_sku_indexed_filename(SKU, 0, ".jpg") == f"{SKU}_1.jpg"
    assert build_sku_indexed_filename(SKU, 2, "jpg") == f"{SKU}_3.jpg"


def test_extract_sku_legacy_and_amazon():
    assert extract_sku_from_image_stem(f"{SKU}_1") == SKU
    assert extract_sku_from_image_stem(f"{SKU}.MAIN") == SKU
    assert extract_sku_from_image_stem(f"{SKU}.PT03") == SKU
    assert extract_sku_from_image_path(f"/tmp/{SKU}_2.jpg") == SKU
    assert extract_sku_from_image_path(f"/tmp/{SKU}.PT01.jpg") == SKU


def test_is_legacy_and_amazon_detection():
    assert is_legacy_sku_filename(f"{SKU}_1.jpg", SKU)
    assert not is_legacy_sku_filename(f"{SKU}.MAIN.jpg", SKU)
    assert is_amazon_sku_filename(f"{SKU}.MAIN.jpg", SKU)
    assert not is_amazon_sku_filename(f"{SKU}_1.jpg", SKU)


def test_product_slots_exclude_first():
    imgs = [_Img("a.jpg"), _Img("b.jpg"), _Img("c.jpg")]
    assert len(product_image_slots_from_sorted_images(imgs, exclude_first=True)) == 2
    assert len(product_image_slots_from_sorted_images(imgs, exclude_first=False)) == 3


def test_plan_rename_skips_legacy_and_assigns_indexed_names():
    imgs = [
        _Img(f"/folder/barcode.jpg"),
        _Img(f"/folder/{SKU}_1.jpg"),
        _Img(f"/folder/IMG_0001.jpg"),
    ]
    ops = plan_amazon_rename_targets(imgs, SKU, exclude_first=True)
    assert len(ops) == 1
    assert ops[0][1].endswith(f"{SKU}_2.jpg")
    assert ops[0][0].path.endswith("IMG_0001.jpg")


def test_plan_rename_exclude_off_first_is_one():
    imgs = [_Img(f"/folder/shot1.jpg"), _Img(f"/folder/shot2.jpg")]
    ops = plan_amazon_rename_targets(imgs, SKU, exclude_first=False)
    assert ops[0][1].endswith(f"{SKU}_1.jpg")
    assert ops[1][1].endswith(f"{SKU}_2.jpg")


def test_needs_rerename_when_first_index_missing():
    imgs = [
        _Img(f"/folder/barcode.jpg"),
        _Img(f"/folder/{SKU}_2.jpg"),
        _Img(f"/folder/{SKU}_3.jpg"),
    ]
    assert needs_amazon_sequence_rerename(imgs, SKU, exclude_first=True)
    assert not needs_amazon_sequence_rerename(
        [
            _Img(f"/folder/barcode.jpg"),
            _Img(f"/folder/{SKU}_1.jpg"),
            _Img(f"/folder/{SKU}_2.jpg"),
        ],
        SKU,
        exclude_first=True,
    )


def test_plan_rerename_shifts_numbers():
    imgs = [
        _Img(f"/folder/barcode.jpg"),
        _Img(f"/folder/{SKU}_2.jpg"),
        _Img(f"/folder/{SKU}_3.jpg"),
        _Img(f"/folder/{SKU}_4.jpg"),
    ]
    ops = plan_amazon_rerename_targets(imgs, SKU, exclude_first=True)
    targets = [op[1].replace("\\", "/") for op in ops]
    assert targets == [
        f"/folder/{SKU}_1.jpg",
        f"/folder/{SKU}_2.jpg",
        f"/folder/{SKU}_3.jpg",
    ]


def test_infer_sku_from_sorted_images():
    imgs = [_Img(f"/x/{SKU}_3.jpg"), _Img("/x/other.jpg")]
    assert infer_sku_from_sorted_images(imgs) == SKU


def test_camera_filename_not_treated_as_sku():
    assert extract_sku_from_image_stem("PXL_20260620_1") is None
    assert extract_sku_from_image_path("/folder/PXL_20260620_1.jpg") is None
    assert not is_legacy_sku_filename("PXL_20260620_1.jpg", "PXL_20260620")
    assert is_legacy_sku_filename(f"{SKU}_1.jpg", SKU)


def test_structured_route_sku_still_detected():
    route_sku = "20260613-HA-29-1545-3P-027"
    assert extract_sku_from_image_stem(f"{route_sku}_1") == route_sku
    assert is_legacy_sku_filename(f"{route_sku}_2.jpg", route_sku)
