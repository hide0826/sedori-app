#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SP-API 出品日・手数料パーサの単体テスト。"""

from __future__ import annotations

from desktop.services.sp_api_listing_fees import (
    apply_listing_fees_to_record,
    format_listed_date,
    listing_is_amazon_fulfilled,
    parse_fees_estimate,
    parse_listing_created_date,
    record_is_fba,
)


def test_format_listed_date_iso():
    assert format_listed_date("2024-03-15T10:00:00.000Z") == "2024/03/15"
    assert format_listed_date("2024/03/15") == "2024/03/15"
    assert format_listed_date("") == ""


def test_parse_listing_created_date():
    body = {
        "summaries": [
            {"marketplaceId": "A1VC38T7YXB528", "createdDate": "2025-01-08T12:34:56Z"}
        ]
    }
    assert parse_listing_created_date(body) == "2025/01/08"


def test_listing_is_amazon_fulfilled():
    assert listing_is_amazon_fulfilled(
        {"fulfillmentAvailability": [{"fulfillmentChannelCode": "AMAZON_JP"}]}
    ) is True
    assert listing_is_amazon_fulfilled(
        {"fulfillmentAvailability": [{"fulfillmentChannelCode": "DEFAULT"}]}
    ) is False


def test_parse_fees_estimate_splits_referral_and_fba():
    body = {
        "payload": {
            "FeesEstimateResult": {
                "Status": "Success",
                "FeesEstimate": {
                    "TotalFeesEstimate": {"Amount": 1234, "CurrencyCode": "JPY"},
                    "FeeDetailList": [
                        {"FeeType": "ReferralFee", "FinalFee": {"Amount": 500}},
                        {
                            "FeeType": "FBAFees",
                            "FinalFee": {"Amount": 734},
                            "FeeDetailList": [
                                {
                                    "FeeType": "FBAPerUnitFulfillmentFee",
                                    "FinalFee": {"Amount": 734},
                                }
                            ],
                        },
                    ],
                },
            }
        }
    }
    platform, fba, status = parse_fees_estimate(body)
    assert status == "Success"
    assert platform == 500
    assert fba == 734


def test_record_is_fba():
    assert record_is_fba({"発送方法": "FBA"}) is True
    assert record_is_fba({"発送方法": "自己発送"}) is False


def test_apply_listing_fees_to_record_recalculates_profit():
    rec = {
        "SKU": "TEST",
        "仕入れ価格": 1000,
        "販売予定価格": 5000,
        "発送方法": "FBA",
    }
    apply_listing_fees_to_record(
        rec,
        listed_date="2025/02/01",
        platform_fee=500,
        fba_shipping_fee=200,
        is_fba=True,
    )
    assert rec["出品日"] == "2025/02/01"
    assert rec["listed_date"] == "2025/02/01"
    assert rec["プラットフォーム手数料"] == 500
    assert rec["出荷費用"] == 200
    assert rec["費用合計"] == 700
    assert rec["損益分岐点"] == 1700
    assert rec["見込み利益"] == 3300
