#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""単品仕入向け: ASIN から商品名・JAN・FBA手数料を SP-API で取る。"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_JP_MARKETPLACE = "A1VC38T7YXB528"
_ID_TYPES = frozenset({"EAN", "JAN", "GTIN", "UPC"})


def catalog_item_body(body: Any) -> Dict[str, Any]:
    """Catalog Items の応答から、商品1件の辞書を取り出す。"""
    if not isinstance(body, dict):
        return {}
    if body.get("summaries") or body.get("identifiers") or body.get("asin"):
        return body
    payload = body.get("payload")
    if isinstance(payload, dict):
        return catalog_item_body(payload)
    items = body.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return body


def extract_catalog_title(body: Any) -> str:
    """カタログ応答から商品名を取る。日本マーケットを優先する。"""
    item = catalog_item_body(body)
    summaries = item.get("summaries") or []
    if isinstance(summaries, dict):
        summaries = [summaries]
    fallback = ""
    for row in summaries:
        if not isinstance(row, dict):
            continue
        name = str(row.get("itemName") or "").strip()
        if not name:
            continue
        if str(row.get("marketplaceId") or "") == _JP_MARKETPLACE:
            return name
        if not fallback:
            fallback = name
    return fallback


def extract_catalog_jan(body: Any) -> str:
    """カタログ応答から JAN（13桁を優先）を取る。"""
    item = catalog_item_body(body)
    candidates: list[str] = []
    blocks = item.get("identifiers") or []
    if isinstance(blocks, dict):
        blocks = [blocks]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        inner = block.get("identifiers")
        rows = inner if isinstance(inner, list) else [block]
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("identifierType") or row.get("type") or "").upper()
            value = str(row.get("identifier") or row.get("value") or "").strip()
            if not value:
                continue
            if kind and kind not in _ID_TYPES:
                continue
            candidates.append(value)
    thirteen = ""
    other = ""
    for code in candidates:
        digits = re.sub(r"\D", "", code)
        if len(digits) == 13 and not thirteen:
            thirteen = digits
        elif len(digits) in (8, 12, 14) and not other:
            other = digits
    return thirteen or other


def lookup_single_purchase_sp_api(
    asin: str,
    listing_price: float = 0,
    *,
    is_fba: bool = True,
    include_catalog: bool = True,
    include_fees: bool = True,
    client: Any = None,
) -> Dict[str, Any]:
    """
    ASIN から商品情報を取る。

    Returns:
        title, jan, platform_fee, fba_shipping_fee, errors
        手数料は販売予定価格が 1 円以上のときだけ取る。
    """
    asin = str(asin or "").strip().upper()
    result: Dict[str, Any] = {
        "title": "",
        "jan": "",
        "platform_fee": None,
        "fba_shipping_fee": None,
        "errors": [],
    }
    if len(asin) != 10:
        result["errors"].append("ASINは10文字で入力してください。")
        return result

    if client is None:
        try:
            from services.sp_api_listing_fees import build_sp_api_client
        except ImportError:
            from desktop.services.sp_api_listing_fees import build_sp_api_client  # type: ignore
        client = build_sp_api_client()

    if include_catalog:
        try:
            body = client.get_catalog_item(
                asin,
                included_data="summaries,identifiers",
            )
            result["title"] = extract_catalog_title(body)
            result["jan"] = extract_catalog_jan(body)
            if not result["title"]:
                result["errors"].append("商品名が見つかりませんでした。")
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"商品名: {exc}")

    price = int(listing_price or 0)
    if include_fees and price > 0:
        try:
            from services.sp_api_listing_fees import parse_fees_estimate
        except ImportError:
            from desktop.services.sp_api_listing_fees import parse_fees_estimate  # type: ignore
        fees_body = client.get_my_fees_estimate_for_asin(
            asin,
            listing_price_yen=price,
            is_amazon_fulfilled=bool(is_fba),
        )
        platform_fee, fba_fee, status = parse_fees_estimate(fees_body)
        if status != "Success" or platform_fee is None:
            result["errors"].append(f"手数料: {status}")
        else:
            result["platform_fee"] = platform_fee
            result["fba_shipping_fee"] = fba_fee
    return result
