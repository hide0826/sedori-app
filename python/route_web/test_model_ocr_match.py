# -*- coding: utf-8 -*-
"""型番 OCR のタイトル照合（Gemini 無し）。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from route_web.model_ocr import is_strong_model, normalize_for_match, title_has_model
from route_web.route_purchases import _rows_matching_model, lookup_photo_model


class ModelMatchTests(unittest.TestCase):
    def test_normalize_strips_hyphen(self) -> None:
        self.assertEqual(normalize_for_match("WH-1000XM4"), normalize_for_match("WH1000XM4"))

    def test_strong_model_rejects_short(self) -> None:
        self.assertFalse(is_strong_model("HG"))
        self.assertFalse(is_strong_model("12"))
        self.assertTrue(is_strong_model("WH-1000XM4"))
        self.assertTrue(is_strong_model("TE-Q3"))

    def test_title_has_model(self) -> None:
        title = "Sony WH-1000XM4 ワイヤレスヘッドホン ブラック"
        self.assertTrue(title_has_model(title, "WH1000XM4"))
        self.assertTrue(title_has_model(title, "WH-1000XM4"))
        self.assertFalse(title_has_model(title, "WH-1000XM5"))
        self.assertFalse(title_has_model(title, "HG"))

    def test_rows_matching_model(self) -> None:
        rows = [
            {"product_name": "Sony WH-1000XM4 ブラック", "sku": "A"},
            {"product_name": "別商品 ABC-123", "sku": "B"},
            {"product_name": "Sony WH1000XM4/B", "sku": "C"},
        ]
        hits = _rows_matching_model(rows, "WH-1000XM4")
        skus = [row["sku"] for row in hits]
        # 正規化後のタイトルが短い方を先に（型番の比重が高い）
        self.assertEqual(set(skus), {"A", "C"})
        self.assertEqual(skus[0], "C")

    def test_lookup_photo_model_route(self) -> None:
        rows = [
            {
                "sku": "TMP-001",
                "jan": "",
                "asin": "B00TEST",
                "product_name": "Audio-Technica ATH-M50x モニターヘッドホン",
            },
            {
                "sku": "TMP-002",
                "jan": "",
                "asin": "B00OTHER",
                "product_name": "別の商品",
            },
        ]
        with patch(
            "route_web.route_purchases.list_route_purchases",
            return_value=rows,
        ), patch(
            "route_web.route_purchases.nearby_route_products",
            return_value=[],
        ):
            looked = lookup_photo_model({"route_date": "2026-11-20"}, "ATH-M50x")
        self.assertEqual(looked["level"], "route")
        self.assertEqual(len(looked["candidates"]), 1)
        self.assertEqual(looked["candidates"][0]["sku"], "TMP-001")

    def test_lookup_rejects_weak_model(self) -> None:
        looked = lookup_photo_model({}, "HG")
        self.assertEqual(looked["level"], "none")
        self.assertEqual(looked["candidates"], [])


if __name__ == "__main__":
    unittest.main()
