#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from desktop.services.customer_support_sku_lookup import (
    _build_authoritative_purchase_record,
    _fill_empty_image_slots,
    lookup_sku_context,
)


class _FakeProductWidget:
    def __init__(self, records):
        self.purchase_all_records = records
        self.purchase_all_records_master = list(records)
        self.purchase_records = list(records)

    def _purchase_record_by_sku(self, sku: str):
        for rec in self.purchase_all_records:
            if (rec.get("SKU") or rec.get("sku") or "").strip() == sku:
                return rec
        return None


def test_lookup_prefers_exact_sku_row_over_product_db_images(tmp_path):
    sku_a = "20240605-SS-20-1780-6P-007"
    sku_b = "20240605-SS-20-1780-6P-008"
    img_a = tmp_path / "img_a.jpg"
    img_b = tmp_path / "img_b.jpg"
    img_a.write_bytes(b"a")
    img_b.write_bytes(b"b")

    records = [
        {
            "SKU": sku_a,
            "ASIN": "B07DWXJCM6",
            "商品名": "商品A",
            "仕入れ価格": 1000,
            "販売予定価格": 3000,
            "発送方法": "FBA",
            "コメント": "SKU-Aコメント",
            "画像1": str(img_a),
        },
        {
            "SKU": sku_b,
            "ASIN": "B07DWXJCM6",
            "商品名": "商品B",
            "仕入れ価格": 1200,
            "コメント": "SKU-Bコメント",
            "画像1": str(img_b),
        },
    ]
    widget = _FakeProductWidget(records)

    ctx_a = lookup_sku_context(sku_a, product_widget=widget, purchase_db=_EmptyDB(), product_db=_ProductDbStub({
        sku_a: {"image_1": str(img_b)},
        sku_b: {"image_1": str(img_b)},
    }))
    ctx_b = lookup_sku_context(sku_b, product_widget=widget, purchase_db=_EmptyDB(), product_db=_ProductDbStub({
        sku_a: {"image_1": str(img_a)},
        sku_b: {"image_1": str(img_a)},
    }))

    assert ctx_a is not None
    assert ctx_b is not None
    assert ctx_a["purchase_price"] == 1000
    assert ctx_a["comment"] == "SKU-Aコメント"
    assert ctx_a["shipping_method"] == "FBA"
    assert len(ctx_a["image_paths"]) == 1
    assert ctx_a["image_paths"][0]["path"] == str(img_a.resolve())

    assert ctx_b["purchase_price"] == 1200
    assert ctx_b["comment"] == "SKU-Bコメント"
    assert len(ctx_b["image_paths"]) == 1
    assert ctx_b["image_paths"][0]["path"] == str(img_b.resolve())


def test_fill_empty_image_slots_does_not_override_existing():
    merged = {"画像1": "/keep/me.jpg"}
    purchase_row = {"image_1": "/other.jpg"}
    product_row = {"image_1": "/other2.jpg"}
    _fill_empty_image_slots(merged, purchase_row, product_row)
    assert merged["画像1"] == "/keep/me.jpg"


def test_build_authoritative_merges_table_over_memory():
    memory = {"SKU": "SKU-1", "仕入れ価格": 500, "画像1": "old.jpg"}
    table = {"SKU": "SKU-1", "画像1": "/full/path/new.jpg", "コメント": "テーブル優先"}

    class _PW:
        purchase_all_records = [memory]

        def _purchase_record_by_sku(self, sku):
            return memory

    # table_record path: monkeypatch via direct call
    from desktop.services import customer_support_sku_lookup as mod

    original = mod.extract_purchase_record_from_purchase_table
    mod.extract_purchase_record_from_purchase_table = lambda _pw, sku: dict(table)
    try:
        rec = _build_authoritative_purchase_record(_PW(), "SKU-1")
    finally:
        mod.extract_purchase_record_from_purchase_table = original

    assert rec is not None
    assert rec["仕入れ価格"] == 500
    assert rec["画像1"] == "/full/path/new.jpg"
    assert rec["コメント"] == "テーブル優先"


class _EmptyDB:
    def get_by_sku(self, sku):
        return None


class _ProductDbStub:
    def __init__(self, images_by_sku):
        self._images_by_sku = images_by_sku

    def get_by_sku(self, sku):
        imgs = self._images_by_sku.get(sku)
        if not imgs:
            return None
        return {"asin": "B07DWXJCM6", "product_name": "共通商品名", **imgs}
