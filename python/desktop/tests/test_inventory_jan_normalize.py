#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inventory_db JAN 正規化の pytest（Track B Phase 0 安全網）。"""

from __future__ import annotations

from desktop.database.inventory_db import normalize_jan_in_record, normalize_jan_in_records


def test_normalize_jan_strips_excel_float_suffix():
    rec = {"JAN": "4970381506544.0", "商品名": "テスト"}
    out = normalize_jan_in_record(rec)
    assert out["JAN"] == "4970381506544"
    assert out is rec  # in-place


def test_normalize_jan_accepts_alternate_keys():
    rec = {"jan": "4901234567890.0"}
    normalize_jan_in_record(rec)
    assert rec["jan"] == "4901234567890"

    rec2 = {"JANコード": "12345.0"}
    normalize_jan_in_record(rec2)
    assert rec2["JANコード"] == "12345"


def test_normalize_jan_empty_and_non_digit():
    rec = {"JAN": ""}
    normalize_jan_in_record(rec)
    assert rec["JAN"] == ""

    rec2 = {"JAN": "ABC.0"}
    normalize_jan_in_record(rec2)
    # 数字以外除去後が空 → None
    assert rec2["JAN"] is None


def test_normalize_jan_in_records_copies():
    records = [
        {"JAN": "111.0", "SKU": "a"},
        {"JAN": "222.0", "SKU": "b"},
    ]
    out = normalize_jan_in_records(records)
    assert out[0]["JAN"] == "111"
    assert out[1]["JAN"] == "222"
    # 元リストは変更しない（copy 経由）
    assert records[0]["JAN"] == "111.0"
