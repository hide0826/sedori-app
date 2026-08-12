#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LedgerDatabase.rename_sku の pytest（仕入SKU変更→古物台帳同期）。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from desktop.database.ledger_db import LedgerDatabase


def test_rename_sku_updates_ledger_entries_and_purchase_rows():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            db.insert_ledger_rows(
                [
                    {
                        "entry_date": "2026-07-01",
                        "counterparty_type": "法人",
                        "counterparty_name": "テスト株式会社",
                        "hinmei": "テスト商品",
                        "qty": 1,
                        "unit_price": 1000,
                        "amount": 1000,
                        "identifier": "B00TEST",
                        "transaction_method": "買受",
                        "sku": "20200712-OLD-SKU-1",
                    }
                ]
            )
            cur = db.conn.cursor()
            cur.execute(
                """
                INSERT INTO purchase_rows (sku, title, qty, unit_price, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("20200712-OLD-SKU-1", "ドラフト商品", 1, 500, "imported"),
            )
            db.conn.commit()

            updated = db.rename_sku("20200712-OLD-SKU-1", "20200713-NEW-SKU-1")
            assert updated == 2

            entries = db.query_ledger("sku = ?", ("20200713-NEW-SKU-1",))
            assert len(entries) == 1
            assert entries[0]["sku"] == "20200713-NEW-SKU-1"

            cur.execute(
                "SELECT sku FROM purchase_rows WHERE sku = ?",
                ("20200713-NEW-SKU-1",),
            )
            assert cur.fetchone()["sku"] == "20200713-NEW-SKU-1"

            cur.execute(
                "SELECT COUNT(*) AS c FROM ledger_entries WHERE sku = ?",
                ("20200712-OLD-SKU-1",),
            )
            assert cur.fetchone()["c"] == 0
        finally:
            db.close()


def test_rename_sku_same_value_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            assert db.rename_sku("SAME", "SAME") == 0
        finally:
            db.close()


def test_rename_sku_requires_both_values():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "hirio_test.db")
        db = LedgerDatabase(db_path=db_path)
        try:
            try:
                db.rename_sku("", "NEW")
                assert False, "expected ValueError"
            except ValueError:
                pass
            try:
                db.rename_sku("OLD", "")
                assert False, "expected ValueError"
            except ValueError:
                pass
        finally:
            db.close()
