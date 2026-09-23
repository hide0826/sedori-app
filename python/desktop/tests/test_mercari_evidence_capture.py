# -*- coding: utf-8 -*-
from desktop.services.mercari_evidence_capture import (
    looks_like_mercari_login,
    normalize_mercari_item_url,
)


def test_normalize_mercari_item_url():
    assert normalize_mercari_item_url(
        "https://jp.mercari.com/item/m97420345081"
    ) == "https://jp.mercari.com/item/m97420345081"
    assert normalize_mercari_item_url("  https://jp.mercari.com/item/m123456789?ref=x ") == (
        "https://jp.mercari.com/item/m123456789"
    )
    assert normalize_mercari_item_url("https://auctions.yahoo.co.jp/jp/auction/x") == ""
    assert normalize_mercari_item_url("") == ""


def test_looks_like_mercari_login():
    assert looks_like_mercari_login("https://login.jp.mercari.com/signin") is True
    assert looks_like_mercari_login(
        "https://jp.mercari.com/item/m97420345081",
        "商品の説明 取引画面を表示する",
    ) is False
    assert looks_like_mercari_login("", "ログイン パスワード") is True
