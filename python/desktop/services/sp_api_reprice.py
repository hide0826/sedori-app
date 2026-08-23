#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
価格改定結果を SP-API Listings Items PATCH で Amazon に反映する。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

try:
    from services.sp_api_orders import build_sp_api_client
except ImportError:
    from desktop.services.sp_api_orders import build_sp_api_client  # type: ignore


def _to_int_price(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "none", "-"):
        return None
    try:
        return int(round(float(text)))
    except (TypeError, ValueError):
        return None


def extract_product_type(listing_body: Dict[str, Any]) -> str:
    """Listings GET レスポンスから productType を取り出す。無ければ PRODUCT。"""
    summaries = listing_body.get("summaries")
    if summaries is None and isinstance(listing_body.get("payload"), dict):
        summaries = listing_body["payload"].get("summaries")
    if isinstance(summaries, list):
        for item in summaries:
            if not isinstance(item, dict):
                continue
            pt = str(item.get("productType") or "").strip()
            if pt:
                return pt
    attrs = listing_body.get("attributes")
    if isinstance(attrs, dict):
        pts = attrs.get("product_type") or attrs.get("productType")
        if isinstance(pts, list) and pts:
            first = pts[0]
            if isinstance(first, dict):
                val = str(first.get("value") or "").strip()
                if val:
                    return val
            elif first:
                return str(first).strip()
    return "PRODUCT"


def collect_price_patch_targets(
    items: Sequence[Mapping[str, Any]],
    *,
    only_changed: bool = True,
) -> List[Dict[str, Any]]:
    """
    改定結果 items から PATCH 対象を抽出する。

    each: {sku, asin, price, new_price, title}
    """
    targets: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        sku = str(raw.get("sku") or raw.get("SKU") or "").strip()
        if not sku or sku in seen:
            continue
        old_p = _to_int_price(raw.get("price"))
        new_p = _to_int_price(raw.get("new_price"))
        if new_p is None or new_p <= 0:
            continue
        if only_changed and old_p is not None and new_p == old_p:
            continue
        seen.add(sku)
        targets.append(
            {
                "sku": sku,
                "asin": str(raw.get("asin") or raw.get("ASIN") or "").strip(),
                "title": str(raw.get("title") or "").strip(),
                "price": old_p,
                "new_price": new_p,
            }
        )
    return targets


def apply_price_patches(
    targets: Sequence[Dict[str, Any]],
    *,
    client: Optional[Any] = None,
    resolve_product_type: bool = True,
    sleep_sec: float = 0.25,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    max_items: Optional[int] = None,
) -> Dict[str, Any]:
    """
    対象 SKU に Listings PATCH を順次送る。

    Returns:
        {success, failed, skipped, total, success_count, failed_count}
    """
    api = client or build_sp_api_client()
    api.ensure_credentials()

    work = list(targets)
    if max_items is not None and max_items >= 0:
        work = work[: int(max_items)]

    success: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    total = len(work)

    for idx, item in enumerate(work, start=1):
        if should_cancel and should_cancel():
            break
        sku = item["sku"]
        new_price = int(item["new_price"])
        if on_progress:
            on_progress(f"価格反映 {idx}/{total}: {sku} → {new_price}")
        product_type = "PRODUCT"
        try:
            if resolve_product_type:
                listing = api.get_listing_item(sku, included_data="summaries")
                product_type = extract_product_type(listing)
            resp = api.patch_listing_price(
                sku,
                new_price,
                product_type=product_type,
            )
            status = str(resp.get("status") or "").upper()
            issues = resp.get("issues") or []
            issue_text = str(issues)
            # 商品タイプ不一致 (4000003) なら PRODUCT で1回だけ再試行
            if product_type != "PRODUCT" and (
                "4000003" in issue_text or "商品タイプ" in issue_text
            ):
                resp = api.patch_listing_price(sku, new_price, product_type="PRODUCT")
                status = str(resp.get("status") or "").upper()
                issues = resp.get("issues") or []
                product_type = f"{product_type}->PRODUCT"
            has_error_issue = isinstance(issues, list) and any(
                str(i.get("severity") or "").upper() == "ERROR"
                for i in issues
                if isinstance(i, dict)
            )
            if status in ("INVALID", "ERROR") or (has_error_issue and status not in ("ACCEPTED", "VALID")):
                failed.append(
                    {
                        **item,
                        "error": f"status={status} issues={str(issues)[:300]}",
                        "product_type": product_type,
                    }
                )
            else:
                success.append({**item, "status": status or "OK", "product_type": product_type})
        except Exception as exc:  # noqa: BLE001
            failed.append({**item, "error": str(exc), "product_type": product_type})
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    return {
        "success": success,
        "failed": failed,
        "skipped": max(0, len(targets) - len(work)),
        "total": total,
        "success_count": len(success),
        "failed_count": len(failed),
    }
