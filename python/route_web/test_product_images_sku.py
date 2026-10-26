# -*- coding: utf-8 -*-
"""同JANの複数SKUが、撮影終了でまとめて消えないこと。"""

from __future__ import annotations

from route_web.product_images import (
    append_route_product_file,
    confirm_route_product_group,
    confirmed_product_groups,
    mark_no_image,
    list_no_image_products,
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


if __name__ == "__main__":
    test_confirm_one_sku_keeps_same_jan_other_sku()
    test_no_image_is_per_sku()
    print("ok")
