#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スタンバイが Amazon登録済みを除外することの unittest。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_DESKTOP = Path(__file__).resolve().parents[1]
if str(_DESKTOP) not in sys.path:
    sys.path.insert(0, str(_DESKTOP))

from services.hit_standby import load_standby_items  # noqa: E402


class StandbyRegisteredExcludeTest(unittest.TestCase):
    def test_skips_amazon_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            purchases = root / "hit_purchases.jsonl"
            purchases.write_text(
                json.dumps(
                    {
                        "token": "TokRegTokReg1",
                        "at": "2026-10-21T10:00:00+09:00",
                        "action": "purchased",
                        "title": "登録済み",
                        "asin": "B0REG",
                        "buy_yen": 1000,
                        "sell_yen": 2000,
                        "image_paths": [],
                        "amazon_registered_at": "2026-10-22T00:00:00+09:00",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "token": "TokOpenTokOpe1",
                        "at": "2026-10-21T11:00:00+09:00",
                        "action": "purchased",
                        "title": "未登録",
                        "asin": "B0OPEN",
                        "buy_yen": 1100,
                        "sell_yen": 2100,
                        "image_paths": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "hit_snapshots").mkdir()
            old = {
                "HIT_PURCHASES_PATH": os.environ.get("HIT_PURCHASES_PATH"),
                "HIT_PURCHASES_IMPORTED_PATH": os.environ.get("HIT_PURCHASES_IMPORTED_PATH"),
                "HIT_SNAPSHOTS_DIR": os.environ.get("HIT_SNAPSHOTS_DIR"),
            }
            try:
                os.environ["HIT_PURCHASES_PATH"] = str(purchases)
                os.environ["HIT_PURCHASES_IMPORTED_PATH"] = str(root / "imported.jsonl")
                os.environ["HIT_SNAPSHOTS_DIR"] = str(root / "hit_snapshots")
                items = load_standby_items(shared=root)
                tokens = {i["token"] for i in items}
                self.assertNotIn("TokRegTokReg1", tokens)
                self.assertIn("TokOpenTokOpe1", tokens)
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
