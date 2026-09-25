#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ取引画面 OCR 切り出しの pytest。"""
from __future__ import annotations

from desktop.services.flea_market_evidence_ocr import (
    listing_url_from_item_id,
    looks_like_transaction_page,
    parse_transaction_ocr_text,
    pick_transaction_text,
)

_SAMPLE_TRANSACTION = """
取引情報
【稼動】 SONY WF-C500 ワイヤレスイヤホン 本体 グリーン
商品代金 ¥1,999
クーポン利用 利用なし
dポイント利用 F149
メルペイ残高利用 ¥1,850
送料込み(出品者負担)
購入日時 2026年8月18日 19:55
配送の方法 ゆうゆうメルカリ便
商品ID m91911023587 コピーする

取引画面
取引が完了しました
ポチ@【毎日値下げ】人気商品を販売中！
良かった

出品者情報
ポチ@【毎日値下げ】人気商品を販売中！
本人確認済
"""

_SAMPLE_LISTING = """
【稼動】SONY WF-C500 ワイヤレスイヤホン 本体 グリーン
¥1,999
取引画面を表示する
商品の説明
"""


def test_parse_mercari_transaction_sample():
    result = parse_transaction_ocr_text(_SAMPLE_TRANSACTION)
    assert result.is_transaction_page is True
    assert result.purchase_datetime == "2026-08-18 19:55"
    assert result.item_id == "m91911023587"
    assert result.listing_url == "https://jp.mercari.com/item/m91911023587"
    assert result.item_price == 1999
    assert "ポチ@" in result.seller_name
    assert "本人確認" not in result.seller_name


def test_seller_name_skips_yu_packet_delivery_label():
    text = """
取引が完了しました
ゆうパケットプラスでお届け
専用資材
出品者情報
ゆうパケットプラスでお届け
よう
本人確認済
出品者レベル10
商品ID m62420345061
"""
    result = parse_transaction_ocr_text(text)
    assert result.seller_name == "よう"


def test_seller_name_skips_yu_packet_size_label():
    text = """
取引が完了しました
サイズ:厚さ7cm以内重さ2kg以内
出品者情報
サイズ:厚さ7cm以内重さ2kg以内
よう
本人確認済
商品ID m62420345061
"""
    result = parse_transaction_ocr_text(text)
    assert result.seller_name == "よう"


def test_listing_page_is_not_transaction():
    assert looks_like_transaction_page(_SAMPLE_LISTING) is False
    result = parse_transaction_ocr_text(_SAMPLE_LISTING)
    assert result.is_transaction_page is False
    assert result.purchase_datetime == ""
    assert result.item_id == ""


def test_fullwidth_digits_and_colon():
    text = "購入日時 ２０２６年８月１８日 １９：５５\n商品ID ｍ９１９１１０２３５８７\n"
    result = parse_transaction_ocr_text(text)
    assert result.purchase_datetime == "2026-08-18 19:55"
    assert result.item_id == "m91911023587"


def test_listing_url_from_item_id():
    assert listing_url_from_item_id("m91911023587") == (
        "https://jp.mercari.com/item/m91911023587"
    )
    assert listing_url_from_item_id("") == ""
    assert listing_url_from_item_id("abc") == ""


def test_pick_transaction_text_prefers_transaction_page():
    chosen = pick_transaction_text([_SAMPLE_LISTING, _SAMPLE_TRANSACTION, ""])
    assert chosen is not None
    assert "購入日時" in chosen
    assert "商品ID" in chosen
