#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FBA受領日（残在庫の一番古い日）の単体テスト。"""

from __future__ import annotations

from datetime import date

from desktop.services.sp_api_receipt_date import (
    apply_receipt_listed_dates,
    events_replacing_range,
    fba_on_hand_by_sku,
    fba_warehouse_on_hand_by_sku,
    listed_dates_for_fba_stock,
    oldest_remaining_receipt_date,
    receipt_events_from_rows,
)


def test_oldest_remaining_skips_sold_receipts():
    events = [
        {"date": "2025-01-01", "qty": 2},
        {"date": "2025-06-01", "qty": 3},
    ]
    assert oldest_remaining_receipt_date(events, 3) == date(2025, 6, 1)
    assert oldest_remaining_receipt_date(events, 4) == date(2025, 1, 1)


def test_on_hand_zero_is_not_updated():
    events = [{"date": "2025-01-01", "qty": 2}]
    assert oldest_remaining_receipt_date(events, 0) is None


def test_incomplete_receipts_are_not_overwritten():
    events = [{"date": "2025-01-01", "qty": 1}]
    assert oldest_remaining_receipt_date(events, 5) is None
    assert oldest_remaining_receipt_date([], 2) is None


def test_merchant_fulfilled_is_excluded():
    rows = [
        {"出品者SKU": "FBA-1", "フルフィルメント・チャンネル": "AMAZON_JP", "在庫数": "2"},
        {"出品者SKU": "MFN-1", "フルフィルメント・チャンネル": "DEFAULT", "在庫数": "4"},
        {"出品者SKU": "EMPTY-1", "フルフィルメント・チャンネル": "AMAZON_JP", "在庫数": "0"},
    ]
    assert fba_on_hand_by_sku(rows) == {"FBA-1": 2}


def test_blank_listings_qty_is_not_warehouse_stock():
    rows = [
        {"出品者SKU": "FBA-1", "フルフィルメント・チャンネル": "AMAZON_JP", "在庫数": "", "数量": ""},
    ]
    assert fba_on_hand_by_sku(rows) == {}


def test_myi_warehouse_qty_counts_fba_only():
    rows = [
        {"sku": "FBA-1", "afn-warehouse-quantity": "3", "afn-fulfillable-quantity": "1"},
        {"sku": "ZERO", "afn-warehouse-quantity": "0"},
        {"sku": "MFN", "mfn-fulfillable-quantity": "4"},
    ]
    assert fba_warehouse_on_hand_by_sku(rows) == {"FBA-1": 3}


def test_ledger_receipt_row_becomes_event():
    events = receipt_events_from_rows(
        [
            {
                "Date": "2025-08-01T00:00:00+00:00",
                "MSKU": "FBA-1",
                "Event Type": "Receipts",
                "Reference ID": "FBA123",
                "Quantity": "2",
                "Fulfillment Center": "NRT1",
            }
        ]
    )
    assert events == [
        {
            "sku": "FBA-1",
            "date": "2025-08-01",
            "qty": 2,
            "shipment_id": "FBA123",
            "fc": "NRT1",
        }
    ]


def test_overlap_refetch_does_not_double_count():
    existing = [{"sku": "FBA-1", "date": "2025-08-01", "qty": 2, "shipment_id": "FBA123", "fc": "NRT1"}]
    fresh = [{"sku": "FBA-1", "date": "2025-08-01", "qty": 2, "shipment_id": "FBA123", "fc": "NRT1"}]
    merged = events_replacing_range(existing, fresh, date(2025, 8, 1), date(2025, 8, 3))
    assert merged[0]["qty"] == 2


def test_listed_dates_only_for_resolved_fba():
    on_hand = fba_on_hand_by_sku(
        [
            {"sku": "FBA-1", "fulfillment-channel": "AMAZON_JP", "quantity": "1"},
            {"sku": "MFN-1", "fulfillment-channel": "DEFAULT", "quantity": "1"},
        ]
    )
    events = [
        {"sku": "FBA-1", "date": "2025-03-02", "qty": 2},
        {"sku": "MFN-1", "date": "2024-01-01", "qty": 1},
    ]
    assert listed_dates_for_fba_stock(on_hand, events) == {"FBA-1": "2025/03/02"}


class _FakePurchaseDb:
    def __init__(self):
        self.rows = {
            "KEEP": {"sku": "KEEP", "listed_date": "2020/01/01", "status": "sold"},
            "READY": {"sku": "READY", "listed_date": "", "status": "ready"},
            "STORE": {"sku": "STORE", "listed_date": "2024/01/01", "status": "storage"},
        }
        self.written = []

    def get_by_sku(self, sku):
        row = self.rows.get(sku)
        return dict(row) if row else None

    def upsert(self, payload):
        self.written.append(dict(payload))
        return 1


def test_apply_overwrites_date_and_sets_selling_only_when_ready():
    db = _FakePurchaseDb()
    summary = apply_receipt_listed_dates(
        db,
        {"KEEP": "2025/08/01", "READY": "2025/09/01", "STORE": "2025/07/01", "MISSING": "2025/01/01"},
    )
    by_sku = {row["sku"]: row for row in db.written}
    assert by_sku["KEEP"]["listed_date"] == "2025/08/01"
    assert "status" not in by_sku["KEEP"]
    assert by_sku["READY"]["status"] == "selling"
    assert by_sku["READY"]["listed_date"] == "2025/09/01"
    assert by_sku["STORE"]["listed_date"] == "2025/07/01"
    assert "status" not in by_sku["STORE"]
    assert summary["skipped_missing"] == 1
    assert summary["status_selling"] == 1
