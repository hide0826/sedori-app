#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hit_standby の単体テスト。"""
from __future__ import annotations

import json
from pathlib import Path

from services.hit_standby import (
    load_standby_items,
    mark_imported,
    purchase_to_inventory_row,
)


def test_purchase_to_inventory_row_has_listing_columns(tmp_path: Path) -> None:
    item = {
        "kind": "purchased",
        "token": "AbCdEfGhIjKl",
        "at": "2026-10-21T12:00:00+09:00",
        "action": "purchased",
        "title": "テスト商品",
        "asin": "B0TESTASIN1",
        "url": "https://jp.mercari.com/item/m123",
        "keyword": "ABC-123",
        "source": "mercari",
        "buy_yen": 3000,
        "sell_yen": 8000,
        "raw": {
            "referral_fee_yen": 800,
            "fba_fulfillment_yen": 500,
            "fba_inbound_shipping_yen": 0,
            "outbound_shipping_yen": 0,
            "misc_cost_yen": 0,
            "fulfillment_mode": "fba",
        },
    }
    row = purchase_to_inventory_row(item)
    assert row["ASIN"] == "B0TESTASIN1"
    assert row["商品名"] == "テスト商品"
    assert row["仕入れ価格"] == 3000
    assert row["販売予定価格"] == 8000
    assert row["仕入チャネル"] == "メルカリ"
    assert row["出品URL"].startswith("https://")
    assert row["SKU"] == "未実装"
    assert row["仕入れ日"] == "2026-10-21"
    assert "見込み利益" in row
    assert "損益分岐点" in row


def test_load_and_mark_imported(tmp_path: Path, monkeypatch) -> None:
    purchases = tmp_path / "hit_purchases.jsonl"
    purchases.write_text(
        json.dumps(
            {
                "token": "TokTokTokTok1",
                "at": "2026-10-21T10:00:00+09:00",
                "action": "purchased",
                "title": "A",
                "asin": "B0AAA",
                "buy_yen": 1000,
                "sell_yen": 2000,
                "image_paths": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "hit_snapshots").mkdir()
    monkeypatch.setenv("HIT_PURCHASES_PATH", str(purchases))
    monkeypatch.setenv("HIT_PURCHASES_IMPORTED_PATH", str(tmp_path / "imported.jsonl"))
    monkeypatch.setenv("HIT_SNAPSHOTS_DIR", str(tmp_path / "hit_snapshots"))
    monkeypatch.setenv("HIRIO_SHARED_DIR", str(tmp_path))

    items = load_standby_items(shared=tmp_path)
    assert len(items) == 1
    assert items[0]["imported"] is False
    mark_imported("TokTokTokTok1", shared=tmp_path)
    items2 = load_standby_items(shared=tmp_path)
    assert items2[0]["imported"] is True
