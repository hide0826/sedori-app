#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LedgerDatabase.update_ledger_entry の pytest。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from desktop.database.ledger_db import LedgerDatabase


def test_update_ledger_entry_changes_fields():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            db.insert_ledger_rows(
                [
                    {
                        "entry_date": "2026-07-11",
                        "counterparty_type": "法人",
                        "counterparty_name": "テスト株式会社",
                        "kobutsu_kind": "道具類",
                        "hinmoku": "道具類",
                        "hinmei": "旧品名",
                        "qty": 1,
                        "unit_price": 1000,
                        "amount": 1000,
                        "identifier": "B00OLD",
                        "transaction_method": "買受",
                        "sku": "20260711-OLD-1",
                        "receipt_no": "",
                    }
                ]
            )
            rows = db.query_ledger()
            assert len(rows) == 1
            entry_id = int(rows[0]["id"])

            ok = db.update_ledger_entry(
                entry_id,
                {
                    "kobutsu_kind": "書籍",
                    "hinmei": "新品名",
                    "sku": "20260712-NEW-1",
                    "receipt_no": "https://example.com/receipt.png",
                    "notes": "手修正",
                },
            )
            assert ok is True

            updated = db.get_ledger_entry_by_id(entry_id)
            assert updated is not None
            assert updated["kobutsu_kind"] == "書籍"
            assert updated["hinmoku"] == "書籍"
            assert updated["hinmei"] == "新品名"
            assert updated["sku"] == "20260712-NEW-1"
            assert updated["receipt_no"] == "https://example.com/receipt.png"
            assert updated["notes"] == "手修正"
        finally:
            db.close()


def test_insert_ledger_keeps_listing_url_and_prefecture():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            db.insert_ledger_rows(
                [
                    {
                        "entry_date": "2026-10-08",
                        "counterparty_type": "フリマ",
                        "platform": "メルカリ",
                        "platform_order_id": "m123",
                        "platform_user": "seller",
                        "listing_url": "https://jp.mercari.com/item/m123",
                        "tracking_no": "1111",
                        "ship_to_prefecture": "東京都",
                        "kobutsu_kind": "道具類",
                        "hinmoku": "道具類",
                        "hinmei": "イヤホン",
                        "qty": 1,
                        "unit_price": 1000,
                        "amount": 1000,
                        "identifier": "B00TEST",
                        "transaction_method": "買受",
                        "sku": "20261008-MERCARI-1",
                    }
                ]
            )
            row = db.query_ledger()[0]
            assert row["listing_url"] == "https://jp.mercari.com/item/m123"
            assert row["tracking_no"] == "1111"
            assert row["ship_to_prefecture"] == "東京都"
        finally:
            db.close()


def test_list_ids_grouped_by_sku_ignores_empty_and_unimplemented():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            db.insert_ledger_rows(
                [
                    {
                        "entry_date": "2026-10-08",
                        "counterparty_type": "フリマ",
                        "hinmei": "A",
                        "sku": "20261008-MERCARI-1",
                        "qty": 1,
                        "unit_price": 100,
                        "amount": 100,
                    },
                    {
                        "entry_date": "2026-10-08",
                        "counterparty_type": "フリマ",
                        "hinmei": "B",
                        "sku": "未実装",
                        "qty": 1,
                        "unit_price": 100,
                        "amount": 100,
                    },
                ]
            )
            grouped = db.list_ids_grouped_by_sku(
                ["20261008-MERCARI-1", "未実装", "", "存在しない"]
            )
            assert len(grouped["20261008-MERCARI-1"]) == 1
            assert "未実装" not in grouped
            assert grouped["存在しない"] == []
        finally:
            db.close()


def test_update_ledger_entry_rejects_bad_id():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            try:
                db.update_ledger_entry(0, {"sku": "X"})
                assert False, "expected ValueError"
            except ValueError:
                pass
        finally:
            db.close()
