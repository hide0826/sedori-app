#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hit_standby の単体テスト。"""
from __future__ import annotations

import json
from pathlib import Path

from services.hit_standby import (
    is_purchase_on_local_date,
    load_standby_items,
    mark_imported,
    normalize_rule369,
    purchase_to_inventory_row,
)
from services.standby_ai_plan import suggest_plan_for_item


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
            "repricing_enabled": 1,
            "ladder_enabled": 1,
            "ladder_rules": json.dumps(
                [
                    {
                        "days_from": 30,
                        "action": "priceTrace",
                        "value": 1,
                        "target_price": 7500,
                        "akaji_drop_percent": 2,
                        "takane_rise_percent": 1,
                    }
                ],
                ensure_ascii=False,
            ),
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
    assert row["コンディション"] == "中古(良い)"  # 旧レコード互換の既定
    assert "見込み利益" in row
    assert "損益分岐点" in row
    assert row["価格改定"] == "ON"
    assert row["repricing_enabled"] == 1
    assert row["ladder_enabled"] == 1
    assert "7500" in str(row.get("ladder_rules") or "")
    assert "[月別ON]" in str(row.get("コメント") or "")


def test_purchase_to_inventory_row_uses_saved_condition() -> None:
    item = {
        "kind": "purchased",
        "token": "CondTokTokTok1",
        "at": "2026-10-28T12:00:00+09:00",
        "action": "purchased",
        "title": "Cond商品",
        "asin": "B0CONDFORMA",
        "url": "https://jp.mercari.com/item/m999",
        "keyword": "XYZ",
        "source": "mercari",
        "buy_yen": 2000,
        "sell_yen": 5000,
        "raw": {
            "condition": "new",
            "condition_label": "新品",
            "condition_amazon": "新品(新品)",
            "condition_note": "【動作確認】問題なく使用できます",
            "referral_fee_yen": 400,
            "fba_fulfillment_yen": 300,
            "fba_inbound_shipping_yen": 0,
            "outbound_shipping_yen": 0,
            "misc_cost_yen": 0,
            "fulfillment_mode": "fba",
        },
    }
    row = purchase_to_inventory_row(item)
    assert row["コンディション"] == "新品(新品)"
    assert row["コンディション説明"] == "【動作確認】問題なく使用できます"


def test_purchase_to_inventory_row_rule_and_tp0() -> None:
    item = {
        "kind": "purchased",
        "token": "RuleTokTokTok1",
        "at": "2026-11-21T12:00:00+09:00",
        "action": "purchased",
        "title": "ルール商品",
        "asin": "B0RULETEST1",
        "url": "https://jp.mercari.com/item/m1",
        "keyword": "KW1",
        "source": "mercari",
        "buy_yen": 2000,
        "sell_yen": 5000,
        "tp1": 4600,
        "tp2": 4400,
        "tp3": 4200,
        "raw": {
            "referral_fee_yen": 400,
            "fba_fulfillment_yen": 300,
            "fba_inbound_shipping_yen": 0,
            "outbound_shipping_yen": 0,
            "misc_cost_yen": 0,
            "fulfillment_mode": "fba",
        },
    }
    row = purchase_to_inventory_row(item, rule369="3", tp0=4800)
    assert str(row["コメント"]).startswith("3 ")
    assert row["3-6-9"] == "3"
    assert row["TP0"] == 4800
    assert row["tp0"] == 4800
    assert row["TP1"] == 4600
    assert row["TP2"] == 4400
    assert row["TP3"] == 4200
    assert normalize_rule369("6P") == "6"
    assert normalize_rule369("9n") == "9"


def test_is_purchase_on_local_date() -> None:
    item = {
        "at": "2026-11-21T09:00:00+09:00",
        "raw": {},
    }
    assert is_purchase_on_local_date(item, "2026-11-21") is True
    assert is_purchase_on_local_date(item, "2026-11-20") is False


def test_suggest_plan_fallback_without_ai() -> None:
    item = {
        "token": "AiTokTokTok12",
        "asin": "B0AITEST0001",
        "title": "AIテスト",
        "buy_yen": 1000,
        "sell_yen": 5000,
        "at": "2026-11-21T10:00:00+09:00",
        "raw": {},
    }
    plan = suggest_plan_for_item(item, use_ai=False)
    assert plan.source == "fallback"
    assert plan.rule369 in ("3", "6", "9")
    assert plan.tp0_yen == 5000


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
