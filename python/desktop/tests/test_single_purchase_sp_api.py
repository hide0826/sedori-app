#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""単品仕入の SP-API 読み取りテスト（通信なし）。"""

from desktop.services.single_purchase_sp_api import (
    extract_catalog_jan,
    extract_catalog_title,
    lookup_single_purchase_sp_api,
)


_CATALOG = {
    "asin": "B08XYZ1234",
    "summaries": [
        {"marketplaceId": "ATVPDKIKX0DER", "itemName": "US name"},
        {"marketplaceId": "A1VC38T7YXB528", "itemName": "日本の商品名"},
    ],
    "identifiers": [
        {
            "marketplaceId": "A1VC38T7YXB528",
            "identifiers": [
                {"identifierType": "EAN", "identifier": "4901234567894"},
                {"identifierType": "ASIN", "identifier": "B08XYZ1234"},
            ],
        }
    ],
}


class _FakeClient:
    def __init__(self):
        self.fee_calls = []

    def get_catalog_item(self, asin, included_data=""):
        assert asin == "B08XYZ1234"
        assert "summaries" in included_data
        return _CATALOG

    def get_my_fees_estimate_for_asin(self, asin, *, listing_price_yen, is_amazon_fulfilled):
        self.fee_calls.append((asin, listing_price_yen, is_amazon_fulfilled))
        return {
            "payload": {
                "FeesEstimateResult": {
                    "Status": "Success",
                    "FeesEstimate": {
                        "FeeDetailList": [
                            {"FeeType": "ReferralFee", "FinalFee": {"Amount": 500}},
                            {"FeeType": "FBAFees", "FinalFee": {"Amount": 734}},
                        ]
                    },
                }
            }
        }


def test_extract_catalog_prefers_japan_title_and_jan():
    assert extract_catalog_title(_CATALOG) == "日本の商品名"
    assert extract_catalog_jan(_CATALOG) == "4901234567894"


def test_lookup_skips_fees_until_price_is_set():
    client = _FakeClient()
    got = lookup_single_purchase_sp_api("b08xyz1234", 0, client=client)
    assert got["title"] == "日本の商品名"
    assert got["jan"] == "4901234567894"
    assert got["platform_fee"] is None
    assert client.fee_calls == []


def test_lookup_reads_fba_fees_for_planned_price():
    client = _FakeClient()
    got = lookup_single_purchase_sp_api(
        "B08XYZ1234",
        3000,
        is_fba=True,
        include_catalog=False,
        client=client,
    )
    assert got["platform_fee"] == 500
    assert got["fba_shipping_fee"] == 734
    assert client.fee_calls == [("B08XYZ1234", 3000, True)]
    assert got["errors"] == []
