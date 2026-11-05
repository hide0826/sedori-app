#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""アマサーチCSV × 購入一覧突合の単体テスト（pytest 不要）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

_DESKTOP = Path(__file__).resolve().parents[1]
if str(_DESKTOP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP))
_SHARED = Path(r"C:\HIRIO\shared")
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from services.hit_amasearch_match import (  # noqa: E402
    DATE_MATCH_DAYS,
    apply_hit_purchase_match,
    normalize_asin,
    parse_inventory_date,
    resolve_box_from_csv_path,
    _pick_purchase,
)


class ParseHelpersTest(unittest.TestCase):
    def test_parse_inventory_date_formats(self) -> None:
        self.assertEqual(parse_inventory_date("2026/10/15 22:53"), date(2026, 10, 15))
        self.assertEqual(
            parse_inventory_date("2026-10-15T22:53:00+09:00"), date(2026, 10, 15)
        )
        self.assertIsNone(parse_inventory_date(""))
        self.assertEqual(normalize_asin("b07vp55n3v"), "B07VP55N3V")

    def test_resolve_box_from_csv_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            box = Path(tmp) / "フリマ20261102"
            csv_dir = box / "仕入CSV"
            csv_dir.mkdir(parents=True)
            csv_path = csv_dir / "amasearch.csv"
            csv_path.write_text("a", encoding="utf-8")
            self.assertEqual(resolve_box_from_csv_path(str(csv_path)), box)


class PickPurchaseTest(unittest.TestCase):
    def test_pick_within_3_days_closest(self) -> None:
        purchases = [
            {
                "token": "TokFarTokFar1",
                "asin": "B0TESTASIN1",
                "at": "2026-10-10T12:00:00+09:00",
                "url": "https://jp.mercari.com/item/m-far",
            },
            {
                "token": "TokNearTokNe1",
                "asin": "B0TESTASIN1",
                "at": "2026-10-15T18:00:00+09:00",
                "url": "https://jp.mercari.com/item/m-near",
            },
            {
                "token": "TokOtherAsin1",
                "asin": "B0OTHERASIN",
                "at": "2026-10-15T12:00:00+09:00",
                "url": "https://jp.mercari.com/item/m-other",
            },
        ]
        picked = _pick_purchase("B0TESTASIN1", date(2026, 10, 16), purchases, set())
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["token"], "TokNearTokNe1")
        self.assertEqual(DATE_MATCH_DAYS, 3)
        self.assertIsNone(
            _pick_purchase("B0TESTASIN1", date(2026, 10, 20), purchases, set())
        )

    def test_pick_allows_registered_for_url_refill(self) -> None:
        """登録済みでもCSV再取込で同じURLを埋められる。未登録があればそちら優先。"""
        purchases = [
            {
                "token": "TokUsedTokUse1",
                "asin": "B0TESTASIN1",
                "at": "2026-10-15T12:00:00+09:00",
                "url": "https://jp.mercari.com/item/m1",
                "amazon_registered_at": "2026-10-16T00:00:00+09:00",
            },
            {
                "token": "TokFreeTokFre1",
                "asin": "B0TESTASIN1",
                "at": "2026-10-15T13:00:00+09:00",
                "url": "https://jp.mercari.com/item/m2",
            },
        ]
        picked = _pick_purchase("B0TESTASIN1", date(2026, 10, 15), purchases, set())
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked["token"], "TokFreeTokFre1")

        # 未登録を使い切ったあとは登録済みでも拾う
        picked2 = _pick_purchase(
            "B0TESTASIN1",
            date(2026, 10, 15),
            purchases,
            {"TokFreeTokFre1"},
        )
        self.assertIsNotNone(picked2)
        assert picked2 is not None
        self.assertEqual(picked2["token"], "TokUsedTokUse1")
        self.assertEqual(picked2["url"], "https://jp.mercari.com/item/m1")

        # 登録済みだけの場合も拾える
        only_reg = _pick_purchase(
            "B0TESTASIN1",
            date(2026, 10, 15),
            [purchases[0]],
            set(),
        )
        self.assertIsNotNone(only_reg)
        assert only_reg is not None
        self.assertEqual(only_reg["token"], "TokUsedTokUse1")


class ApplyMatchTest(unittest.TestCase):
    def test_apply_fills_url_and_marks_registered(self) -> None:
        import hit_snapshot as hs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            purchases = root / "hit_purchases.jsonl"
            snaps = root / "hit_snapshots"
            snaps.mkdir()
            token = "ApplyTokApply1"
            purchases.write_text(
                json.dumps(
                    {
                        "token": token,
                        "at": "2026-10-15T22:00:00+09:00",
                        "action": "purchased",
                        "asin": "B07VP55N3V",
                        "url": "https://jp.mercari.com/item/m999",
                        "title": "テストドライヤー",
                        "buy_yen": 2800,
                        "sell_yen": 5000,
                        "image_paths": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            shared = _SHARED if _SHARED.is_dir() else root
            with mock.patch.object(hs, "PURCHASES_PATH", purchases), mock.patch.object(
                hs, "purchases_path", return_value=purchases
            ), mock.patch.object(hs, "SNAPSHOTS_DIR", snaps), mock.patch.object(
                hs, "snapshots_dir", return_value=snaps
            ), mock.patch(
                "services.hit_amasearch_match._ensure_shared_on_path",
                return_value=shared,
            ):
                df = pd.DataFrame(
                    [
                        {
                            "仕入れ日": "2026/10/15 22:53",
                            "ASIN": "B07VP55N3V",
                            "JAN": "",
                            "SKU": "未実装",
                            "商品名": "パナソニック",
                            "出品URL": "",
                        }
                    ]
                )
                result = apply_hit_purchase_match(df, csv_paths=[])
                self.assertEqual(result.url_filled, 1)
                self.assertEqual(df.at[0, "出品URL"], "https://jp.mercari.com/item/m999")
                self.assertEqual(result.registered, 1)
                again = hs.find_purchase(token)
                self.assertIsNotNone(again)
                assert again is not None
                self.assertTrue(hs.is_amazon_registered(again))


if __name__ == "__main__":
    unittest.main()
