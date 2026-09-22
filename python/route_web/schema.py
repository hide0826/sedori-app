# -*- coding: utf-8 -*-
"""route.json の生成ヘルパー（デスクトップからも利用）。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

try:
    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # pragma: no cover
    JST = timezone(timedelta(hours=9))


def build_route_document(
    *,
    web_id: str,
    folder_path: str,
    route_date: str,
    route_code: str,
    route_name: str,
    stores: List[Dict[str, Any]],
    departure_time: str = "",
    return_time: str = "",
    toll_outbound: str = "",
    toll_return: str = "",
    parking: str = "",
    food: str = "",
    other_expense: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    store_rows: List[Dict[str, Any]] = []
    for idx, store in enumerate(stores, start=1):
        code = str(
            store.get("store_code")
            or store.get("supplier_code")
            or ""
        ).strip()
        if not code:
            continue
        order = store.get("visit_order")
        try:
            order_i = int(order) if order is not None else idx
        except (TypeError, ValueError):
            order_i = idx
        raw_count = store.get("purchase_item_count")
        purchase_item_count: Optional[int] = None
        if raw_count is not None and str(raw_count).strip() != "":
            try:
                purchase_item_count = int(raw_count)
            except (TypeError, ValueError):
                purchase_item_count = None

        store_rows.append(
            {
                "order": order_i,
                "store_code": code,
                "store_name": str(store.get("store_name") or "").strip(),
                "in_time": str(store.get("store_in_time") or store.get("in_time") or "").strip(),
                "out_time": str(store.get("store_out_time") or store.get("out_time") or "").strip(),
                "purchase_item_count": purchase_item_count,
                "notes": str(store.get("notes") or "").strip(),
            }
        )
    store_rows.sort(key=lambda r: (r["order"], r["store_code"]))

    now = datetime.now(JST).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "web_id": web_id,
        "folder_path": folder_path,
        "route_date": route_date,
        "route_code": route_code or "",
        "route_name": route_name or "",
        "departure_time": departure_time or "",
        "return_time": return_time or "",
        "toll_outbound": toll_outbound or "",
        "toll_return": toll_return or "",
        "parking": parking or "",
        "food": food or "",
        "other_expense": other_expense or "",
        "notes": notes or "",
        "updated_at": now,
        "stores": store_rows,
    }


def stamp_updated(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["updated_at"] = datetime.now(JST).isoformat(timespec="seconds")
    return out
