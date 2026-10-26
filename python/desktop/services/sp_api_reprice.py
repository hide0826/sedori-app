#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
価格改定結果を SP-API で Amazon に反映する。

既定は JSON_LISTINGS_FEED 一括。失敗 SKU は Listings PATCH にフォールバック。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from services.sp_api_orders import build_sp_api_client
except ImportError:
    from desktop.services.sp_api_orders import build_sp_api_client  # type: ignore

try:
    from sp_api_client import MARKETPLACE_ID_JP, SpApiError
except ImportError:  # pragma: no cover
    MARKETPLACE_ID_JP = "A1VC38T7YXB528"

    class SpApiError(Exception):
        pass


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
    改定結果 items から PATCH / Feed 対象を抽出する。

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


def build_json_listings_price_feed(
    targets: Sequence[Mapping[str, Any]],
    seller_id: str,
    *,
    marketplace_id: str = MARKETPLACE_ID_JP,
    currency_code: str = "JPY",
) -> Dict[str, Any]:
    """価格更新用 JSON_LISTINGS_FEED ペイロードを組み立てる。"""
    sid = (seller_id or "").strip()
    if not sid:
        raise ValueError("seller_id が必要です。")
    messages: List[Dict[str, Any]] = []
    for item in targets:
        sku = str(item.get("sku") or "").strip()
        new_price = _to_int_price(item.get("new_price"))
        if not sku or new_price is None or new_price <= 0:
            continue
        messages.append(
            {
                "messageId": len(messages) + 1,
                "sku": sku,
                "operationType": "PATCH",
                "productType": "PRODUCT",
                "patches": [
                    {
                        "op": "replace",
                        "path": "/attributes/purchasable_offer",
                        "value": [
                            {
                                "marketplace_id": marketplace_id,
                                "currency": currency_code,
                                "audience": "ALL",
                                "our_price": [
                                    {
                                        "schedule": [
                                            {
                                                "value_with_tax": new_price,
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    return {
        "header": {
            "sellerId": sid,
            "version": "2.0",
            "issueLocale": "ja_JP",
        },
        "messages": messages,
    }


def _message_id_map(
    targets: Sequence[Mapping[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    mapping: Dict[int, Dict[str, Any]] = {}
    for idx, item in enumerate(targets, start=1):
        mapping[idx] = dict(item)
    return mapping


def parse_listings_feed_result(
    result_json: Optional[Mapping[str, Any]],
    id_to_target: Mapping[int, Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Feed 結果 JSON を success / failed に振り分ける。

    ERROR severity の issue がある messageId を failed。結果が無い／issues 無しは成功扱い。
    """
    failed_ids: Dict[int, str] = {}
    if isinstance(result_json, Mapping):
        issues = result_json.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                severity = str(issue.get("severity") or "").upper()
                if severity != "ERROR":
                    continue
                mid_raw = issue.get("messageId")
                try:
                    mid = int(mid_raw)
                except (TypeError, ValueError):
                    continue
                code = str(issue.get("code") or "").strip()
                msg = str(issue.get("message") or "").strip()
                failed_ids[mid] = f"code={code} {msg}".strip()

    success: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for mid, item in id_to_target.items():
        row = dict(item)
        row["product_type"] = "PRODUCT"
        if mid in failed_ids:
            failed.append({**row, "error": failed_ids[mid], "message_id": mid})
        else:
            success.append({**row, "status": "FEED_OK", "message_id": mid})
    return success, failed


def _apply_price_patches_sequential(
    targets: Sequence[Dict[str, Any]],
    *,
    api: Any,
    resolve_product_type: bool = True,
    sleep_sec: float = 0.25,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Listings PATCH を SKU ごとに順次送る（旧経路・フォールバック用）。"""
    success: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    total = len(targets)

    for idx, item in enumerate(targets, start=1):
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
        "total": total,
        "success_count": len(success),
        "failed_count": len(failed),
    }


def _apply_price_feed(
    targets: Sequence[Dict[str, Any]],
    *,
    api: Any,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    poll_sec: float = 5.0,
    timeout_sec: float = 900.0,
    fallback_patch: bool = True,
) -> Dict[str, Any]:
    """JSON_LISTINGS_FEED で一括反映。失敗 SKU は PATCH フォールバック。"""
    if should_cancel and should_cancel():
        return {
            "success": [],
            "failed": [],
            "skipped": len(targets),
            "total": 0,
            "success_count": 0,
            "failed_count": 0,
            "transport": "feed",
        }

    seller_id = str(getattr(getattr(api, "credentials", None), "seller_id", "") or "").strip()
    if not seller_id and hasattr(api, "_require_seller_id"):
        seller_id = str(api._require_seller_id())
    if not seller_id:
        raise SpApiError("Feeds 送信には seller_id が必要です。")

    payload = build_json_listings_price_feed(targets, seller_id)
    messages = payload.get("messages") or []
    if not messages:
        return {
            "success": [],
            "failed": [],
            "skipped": 0,
            "total": 0,
            "success_count": 0,
            "failed_count": 0,
            "transport": "feed",
        }

    # messageId は build 内で 1..N（スキップ無しの targets 前提）。空SKU除外後に合わせる
    work = [
        t
        for t in targets
        if str(t.get("sku") or "").strip() and (_to_int_price(t.get("new_price")) or 0) > 0
    ]
    id_map = _message_id_map(work)

    if on_progress:
        on_progress(f"Feeds 一括送信 {len(work)} 件…")
    try:
        submitted = api.submit_json_listings_feed(
            payload,
            wait=True,
            poll_sec=poll_sec,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:  # noqa: BLE001
        if on_progress:
            on_progress(f"Feeds 失敗: {exc}")
        failed = [{**dict(t), "error": str(exc), "product_type": "PRODUCT"} for t in work]
        if fallback_patch and failed:
            if on_progress:
                on_progress(f"PATCH フォールバック {len(failed)} 件…")
            patched = _apply_price_patches_sequential(
                failed,
                api=api,
                resolve_product_type=False,
                should_cancel=should_cancel,
                on_progress=on_progress,
            )
            return {
                "success": list(patched.get("success") or []),
                "failed": list(patched.get("failed") or []),
                "skipped": 0,
                "total": len(work),
                "success_count": int(patched.get("success_count") or 0),
                "failed_count": int(patched.get("failed_count") or 0),
                "transport": "feed+patch",
                "feed_error": str(exc),
            }
        return {
            "success": [],
            "failed": failed,
            "skipped": 0,
            "total": len(work),
            "success_count": 0,
            "failed_count": len(failed),
            "transport": "feed",
            "feed_error": str(exc),
        }

    feed_id = str(submitted.get("feedId") or "")
    if on_progress:
        on_progress(f"Feeds 完了 feedId={feed_id}")

    result_json = submitted.get("result")
    success, failed = parse_listings_feed_result(
        result_json if isinstance(result_json, dict) else None,
        id_map,
    )

    if fallback_patch and failed:
        if on_progress:
            on_progress(f"PATCH フォールバック {len(failed)} 件…")
        retry_targets = [
            {
                "sku": f["sku"],
                "asin": f.get("asin"),
                "title": f.get("title"),
                "price": f.get("price"),
                "new_price": f["new_price"],
            }
            for f in failed
            if f.get("sku") and f.get("new_price") is not None
        ]
        patched = _apply_price_patches_sequential(
            retry_targets,
            api=api,
            resolve_product_type=False,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
        recovered = list(patched.get("success") or [])
        still_failed = list(patched.get("failed") or [])
        success = list(success) + recovered
        failed = still_failed
        transport = "feed+patch"
    else:
        transport = "feed"

    return {
        "success": success,
        "failed": failed,
        "skipped": 0,
        "total": len(work),
        "success_count": len(success),
        "failed_count": len(failed),
        "transport": transport,
        "feedId": feed_id,
    }


def apply_price_patches(
    targets: Sequence[Dict[str, Any]],
    *,
    client: Optional[Any] = None,
    resolve_product_type: bool = True,
    sleep_sec: float = 0.25,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    max_items: Optional[int] = None,
    transport: str = "feed",
    feed_fallback_patch: bool = True,
    feed_poll_sec: float = 5.0,
    feed_timeout_sec: float = 900.0,
) -> Dict[str, Any]:
    """
    対象 SKU の価格を Amazon に反映する。

    transport:
      - feed（既定）: JSON_LISTINGS_FEED 一括。失敗 SKU は PATCH フォールバック
      - patch: 従来の Listings PATCH 連打

    Returns:
        {success, failed, skipped, total, success_count, failed_count, ...}
    """
    api = client or build_sp_api_client()
    api.ensure_credentials()

    work = list(targets)
    if max_items is not None and max_items >= 0:
        work = work[: int(max_items)]

    mode = str(transport or "feed").strip().lower()
    if mode not in ("feed", "patch"):
        raise ValueError(f"transport は feed または patch: {transport!r}")

    if mode == "patch":
        result = _apply_price_patches_sequential(
            work,
            api=api,
            resolve_product_type=resolve_product_type,
            sleep_sec=sleep_sec,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
        result["skipped"] = max(0, len(targets) - len(work))
        result["transport"] = "patch"
        return result

    result = _apply_price_feed(
        work,
        api=api,
        should_cancel=should_cancel,
        on_progress=on_progress,
        poll_sec=feed_poll_sec,
        timeout_sec=feed_timeout_sec,
        fallback_patch=feed_fallback_patch,
    )
    result["skipped"] = max(0, len(targets) - len(work))
    return result
