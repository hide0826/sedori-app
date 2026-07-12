#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReceiptService.parse_receipt_text の日付・時刻抽出テスト（DB/OCR 未初期化）。"""

from desktop.services.receipt_service import ReceiptService


def _parser() -> ReceiptService:
    """通常 __init__ は DB/OCR を開くため、parse 専用の空インスタンスを作る。"""
    return object.__new__(ReceiptService)


def test_parse_yyyy_mm_dd_date_and_time():
    text = """
    店舗名テスト
    2024/06/06 14:30
    合計 1,200
    """
    result = _parser().parse_receipt_text(text)
    assert result.purchase_date == "2024/06/06"
    assert result.purchase_time == "14:30"


def test_parse_reiwa_date():
    text = """
    令和7年1月15日
    10:05
    """
    result = _parser().parse_receipt_text(text)
    assert result.purchase_date == "2025/01/15"
    assert result.purchase_time == "10:05"


def test_parse_dotted_date():
    text = "買上日 2023.12.01\n09:00\n"
    result = _parser().parse_receipt_text(text)
    assert result.purchase_date == "2023/12/01"
    assert result.purchase_time == "09:00"
