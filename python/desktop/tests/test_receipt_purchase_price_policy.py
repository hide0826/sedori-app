#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レシート→仕入DB 金額更新ポリシーの純関数テスト。"""

from desktop.services.receipt_purchase_price_policy import (
    RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
    is_acceptable_price_difference,
)


def test_tolerance_constant_is_30():
    assert RECEIPT_PRICE_DIFFERENCE_TOLERANCE == 30


def test_acceptable_at_boundaries():
    assert is_acceptable_price_difference(0) is True
    assert is_acceptable_price_difference(30) is True
    assert is_acceptable_price_difference(-30) is True


def test_unacceptable_above_tolerance():
    assert is_acceptable_price_difference(31) is False
    assert is_acceptable_price_difference(-31) is False


def test_none_and_non_numeric_are_false():
    assert is_acceptable_price_difference(None) is False
    assert is_acceptable_price_difference("abc") is False
    assert is_acceptable_price_difference("") is False


def test_string_numbers_are_accepted():
    assert is_acceptable_price_difference("15") is True
    assert is_acceptable_price_difference("15.4") is True
