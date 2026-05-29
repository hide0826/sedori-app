#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析ランキング集計サービス

店舗・ルートのランキングデータを集計する。
- 店舗の訪問回数・累計粗利・スコア: 店舗スコアタブと同じ get_merged_store_aggregates
- ルート: 期間内の route_summaries
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.store_score_service import (
    _is_code_like_route_name,
    get_merged_store_aggregates,
)


def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _stores_from_store_score(
    route_db: Any,
    route_visit_db: Any,
    store_db: Any,
) -> List[Dict[str, Any]]:
    """店舗スコアタブと同一ロジックで店舗一覧を構築"""
    rows = get_merged_store_aggregates(route_db, route_visit_db, store_db)
    stores: List[Dict[str, Any]] = []
    for row in rows:
        code = (row.get("store_code") or "").strip()
        if not code:
            continue
        stores.append({
            "store_code": code,
            "store_name": (row.get("store_name") or "").strip(),
            "route_name": (row.get("route_name") or "").strip(),
            "visit_count": _safe_int(row.get("visit_count")),
            "total_gross_profit": _safe_float(row.get("total_gross_profit")),
            "total_item_count": _safe_int(row.get("total_item_count")),
            "avg_rating": _safe_float(row.get("avg_rating")),
            "score": _safe_float(row.get("score")),
        })
    return stores


def _aggregate_routes(
    routes: List[Dict[str, Any]],
    store_db: Any,
) -> List[Dict[str, Any]]:
    """ルートコード単位にサマリーを合算"""
    route_name_by_code: Dict[str, str] = {}
    if store_db:
        try:
            list_fn = getattr(store_db, "list_routes_with_store_count", None)
            if callable(list_fn):
                for r in list_fn() or []:
                    rc = (r.get("route_code") or "").strip()
                    rn = (r.get("route_name") or "").strip()
                    if rc and rn:
                        route_name_by_code[rc] = rn
        except Exception:
            pass

    merged: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        code = (route.get("route_code") or "").strip()
        if not code:
            continue
        display = (route.get("route_display_name") or "").strip()
        label = display or route_name_by_code.get(code) or code
        if _is_code_like_route_name(label) and route_name_by_code.get(code):
            label = route_name_by_code[code]
        if code not in merged:
            merged[code] = {
                "route_code": code,
                "route_name": label,
                "total_gross_profit": 0.0,
                "total_sales_amount": 0.0,
                "total_purchase_amount": 0.0,
                "route_count": 0,
            }
        m = merged[code]
        m["total_gross_profit"] += _safe_float(route.get("total_gross_profit"))
        m["total_sales_amount"] += _safe_float(route.get("total_sales_amount"))
        m["total_purchase_amount"] += _safe_float(route.get("total_purchase_amount"))
        m["route_count"] += 1
        if display and not _is_code_like_route_name(display):
            m["route_name"] = display

    result: List[Dict[str, Any]] = []
    for m in merged.values():
        sales = m["total_sales_amount"]
        profit = m["total_gross_profit"]
        margin = (profit / sales * 100) if sales > 0 else 0.0
        m["expected_margin"] = round(margin, 2)
        result.append(m)
    return result


def _top_n(rows: List[Dict[str, Any]], key: str, top_n: int = 10) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda x: _safe_float(x.get(key)), reverse=True)[:top_n]


def build_ranking_boards(
    route_db: Any,
    route_visit_db: Any,
    store_db: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 10,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    カンバン5列分のランキングデータを返す。

    Returns:
        store_profit, store_visits, store_score,
        route_margin, route_profit
    """
    stores = _stores_from_store_score(route_db, route_visit_db, store_db)

    routes_raw: List[Dict[str, Any]] = []
    if route_db and hasattr(route_db, "list_route_summaries"):
        try:
            routes_raw = route_db.list_route_summaries(
                start_date=start_date,
                end_date=end_date,
            ) or []
        except Exception:
            routes_raw = []
    routes = _aggregate_routes(routes_raw, store_db)

    return {
        "store_profit": _top_n(stores, "total_gross_profit", top_n),
        "store_visits": _top_n(stores, "visit_count", top_n),
        "store_score": _top_n(stores, "score", top_n),
        "route_margin": _top_n(routes, "expected_margin", top_n),
        "route_profit": _top_n(routes, "total_gross_profit", top_n),
    }
