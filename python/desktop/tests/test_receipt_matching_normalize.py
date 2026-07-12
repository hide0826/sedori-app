#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReceiptMatchingService の静的正規化メソッドのテスト（DB非依存）。"""

from desktop.services.receipt_matching_service import ReceiptMatchingService


def test_normalize_text_nfkc_and_strip():
    assert ReceiptMatchingService._normalize_text("  ＡＢＣ  ") == "ABC"
    assert ReceiptMatchingService._normalize_text("") == ""
    assert ReceiptMatchingService._normalize_text(None) == ""


def test_normalize_phone_empty_is_none():
    assert ReceiptMatchingService._normalize_phone(None) is None
    assert ReceiptMatchingService._normalize_phone("") is None


def test_normalize_phone_10_and_11_digits():
    assert ReceiptMatchingService._normalize_phone("0312345678") == "03-1234-5678"
    assert ReceiptMatchingService._normalize_phone("09012345678") == "090-1234-5678"


def test_normalize_phone_fullwidth_and_noise():
    assert ReceiptMatchingService._normalize_phone("０９０−１２３４−５６７８") == "090-1234-5678"
    assert ReceiptMatchingService._normalize_phone("TEL:090-1234-5678") == "090-1234-5678"


def test_calc_items_total_uses_quantity_and_price():
    items = [
        {"quantity": 2, "purchase_price": 100},
        {"仕入れ個数": 1, "仕入れ価格": 50},
    ]
    assert ReceiptMatchingService._calc_items_total(items) == 250


def test_calc_items_total_ignores_invalid_rows():
    items = [
        {"quantity": "x", "purchase_price": 100},
        {"quantity": 1, "purchase_price": 200},
    ]
    assert ReceiptMatchingService._calc_items_total(items) == 200
