#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API Product Pricing（getItemOffers）から同コンディション最安を取る。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from services.sp_api_orders import build_sp_api_client
except ImportError:
    from desktop.services.sp_api_orders import build_sp_api_client  # type: ignore


# Amazon 出品 condition コード → (ItemCondition, SubCondition)
# 1=中古ほぼ新品 2=非常に良い 3=良い 4=可 11=新品
_CONDITION_MAP: Dict[int, Tuple[str, str]] = {
    1: ("Used", "Mint"),
    2: ("Used", "VeryGood"),
    3: ("Used", "Good"),
    4: ("Used", "Acceptable"),
    5: ("Collectible", "CollectibleLikeNew"),
    6: ("Collectible", "CollectibleVeryGood"),
    7: ("Collectible", "CollectibleGood"),
    8: ("Collectible", "CollectibleAcceptable"),
    10: ("Refurbished", "Refurbished"),
    11: ("New", "New"),
}

# ほぼ新品は API によって Mint / LikeNew のどちらか
_SUB_ALIASES: Dict[str, frozenset] = {
    "Mint": frozenset({"mint", "likenew", "like_new", "collectiblelikenew"}),
    "VeryGood": frozenset({"verygood", "very_good", "collectibleverygood"}),
    "Good": frozenset({"good", "collectiblegood"}),
    "Acceptable": frozenset({"acceptable", "collectibleacceptable"}),
    "New": frozenset({"new"}),
    "Refurbished": frozenset({"refurbished", "refurbishedrefurbished"}),
}


def _payload(body: Dict[str, Any]) -> Dict[str, Any]:
    payload = body.get("payload")
    if isinstance(payload, dict):
        return payload
    return body if isinstance(body, dict) else {}


def _to_int_money(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("Amount")
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "none", "-"):
        return None
    try:
        n = int(round(float(text)))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_listing_condition_code(raw: Any) -> int:
    """出品レポート / 仕入DB のコンディションを 1〜11 に正規化する。"""
    if raw is None:
        return 0
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none"):
        return 0
    try:
        code = int(float(text.replace(",", "")))
        if code in _CONDITION_MAP:
            return code
    except (TypeError, ValueError):
        pass
    t = text.replace(" ", "").lower()
    if "新品" in text or t in ("new",):
        return 11
    if "ほぼ新品" in text or "likenew" in t or "mint" in t:
        return 1
    if "非常に良い" in text or "verygood" in t:
        return 2
    if "良い" in text or t == "good":
        return 3
    if "可" in text or "acceptable" in t:
        return 4
    return 0


def item_condition_for_code(code: int) -> str:
    pair = _CONDITION_MAP.get(int(code or 0))
    return pair[0] if pair else "Used"


def sub_condition_for_code(code: int) -> str:
    pair = _CONDITION_MAP.get(int(code or 0))
    return pair[1] if pair else "Good"


def _norm_sub(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _sub_matches(offer_sub: Any, wanted: str) -> bool:
    got = _norm_sub(offer_sub)
    if not got:
        return False
    aliases = _SUB_ALIASES.get(wanted) or frozenset({_norm_sub(wanted)})
    return got in aliases or got == _norm_sub(wanted)


def _offer_landed(offer: Mapping[str, Any]) -> Optional[int]:
    lp = _to_int_money(offer.get("ListingPrice") or offer.get("listingPrice"))
    ship = _to_int_money(offer.get("Shipping") or offer.get("shipping")) or 0
    if lp is None:
        landed = offer.get("LandedPrice") or offer.get("landedPrice")
        return _to_int_money(landed)
    return lp + max(0, ship)


def min_same_condition_from_offers(
    body: Dict[str, Any],
    *,
    wanted_sub: str,
    exclude_seller_id: str = "",
) -> Optional[int]:
    """
    getItemOffers レスポンスから、指定 SubCondition の最安（本体+送料）を返す。
    自社 SellerId は除外する。
    """
    payload = _payload(body)
    offers = payload.get("Offers") or payload.get("offers") or []
    if not isinstance(offers, list):
        return None
    own = str(exclude_seller_id or "").strip()
    mins: List[int] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        seller = str(offer.get("SellerId") or offer.get("sellerId") or "").strip()
        if own and seller and seller == own:
            continue
        sub = offer.get("SubCondition") or offer.get("subCondition") or ""
        if wanted_sub and not _sub_matches(sub, wanted_sub):
            continue
        landed = _offer_landed(offer)
        if landed is not None:
            mins.append(landed)
    if not mins:
        return None
    return min(mins)


def _asin_from_batch_response(resp: Mapping[str, Any]) -> str:
    body = resp.get("body") if isinstance(resp.get("body"), dict) else resp
    payload = _payload(body) if isinstance(body, dict) else {}
    asin = str(payload.get("ASIN") or payload.get("asin") or "").strip().upper()
    if asin:
        return asin
    # request 側の URI から拾う
    req = resp.get("request") if isinstance(resp.get("request"), dict) else {}
    uri = str(req.get("uri") or "").strip()
    if "/items/" in uri and "/offers" in uri:
        try:
            mid = uri.split("/items/", 1)[1].split("/offers", 1)[0]
            return mid.strip().upper()
        except IndexError:
            return ""
    return ""


def fetch_min_prices_for_asins(
    specs: Sequence[Mapping[str, Any]],
    *,
    client: Optional[Any] = None,
    exclude_seller_id: Optional[str] = None,
    sleep_sec: float = 0.4,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Optional[int]]:
    """
    ASIN ごとの同コンディション最安。

    specs: {asin, condition_code} のリスト（asin 重複可・先勝ち）
    Returns: {ASIN: min_price_or_None}
    """
    api = client or build_sp_api_client()
    api.ensure_credentials()
    own = (exclude_seller_id if exclude_seller_id is not None else (api.credentials.seller_id or "")).strip()

    unique: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for spec in specs:
        asin = str(spec.get("asin") or spec.get("ASIN") or "").strip().upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        code = parse_listing_condition_code(spec.get("condition_code") or spec.get("condition"))
        unique.append(
            {
                "asin": asin,
                "code": code,
                "item_condition": item_condition_for_code(code),
                "sub": sub_condition_for_code(code),
            }
        )

    result: Dict[str, Optional[int]] = {u["asin"]: None for u in unique}
    total = len(unique)
    idx = 0
    batch_size = 20
    while idx < total:
        if should_cancel and should_cancel():
            break
        chunk = unique[idx : idx + batch_size]
        idx += len(chunk)
        if on_progress:
            on_progress(f"最安取得 {min(idx, total)}/{total}")
        try:
            raw = api.get_item_offers_batch(
                [{"asin": c["asin"], "item_condition": c["item_condition"]} for c in chunk]
            )
        except Exception:
            raw = {"responses": []}
        responses = raw.get("responses")
        if responses is None and isinstance(raw.get("payload"), dict):
            responses = raw["payload"].get("responses")
        if not isinstance(responses, list):
            responses = []

        by_asin: Dict[str, Dict[str, Any]] = {}
        for resp in responses:
            if not isinstance(resp, dict):
                continue
            asin = _asin_from_batch_response(resp)
            body = resp.get("body") if isinstance(resp.get("body"), dict) else resp
            if asin and isinstance(body, dict):
                by_asin[asin] = body

        for c in chunk:
            asin = c["asin"]
            body = by_asin.get(asin)
            if body is None:
                # バッチで取れなければ1件ずつ
                try:
                    body = api.get_item_offers(asin, item_condition=c["item_condition"])
                except Exception:
                    body = {}
            result[asin] = min_same_condition_from_offers(
                body if isinstance(body, dict) else {},
                wanted_sub=c["sub"],
                exclude_seller_id=own,
            )
        if sleep_sec > 0 and idx < total:
            time.sleep(sleep_sec)
    return result
