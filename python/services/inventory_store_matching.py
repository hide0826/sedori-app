#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入データとルートサマリーの店舗照合（PySide6 非依存）。"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    from desktop.database.route_db import RouteDatabase
except ImportError:
    from database.route_db import RouteDatabase
from services.route_matching_service import RouteMatchingService


class InventoryStoreMatchingError(Exception):
    """照合処理の入力・DBエラー。"""


def attach_route_date_to_store_visits(
    route_summary: Dict[str, Any], store_visits: List[Dict[str, Any]]
) -> None:
    route_date = route_summary.get("route_date", "")
    if not route_date:
        return
    for visit in store_visits:
        in_time = visit.get("store_in_time", "")
        out_time = visit.get("store_out_time", "")
        if in_time and ":" in in_time and len(in_time.split(" ")) == 1:
            visit["store_in_time"] = f"{route_date} {in_time}:00" if ":" in in_time else in_time
        if out_time and ":" in out_time and len(out_time.split(" ")) == 1:
            visit["store_out_time"] = f"{route_date} {out_time}:00" if ":" in out_time else out_time


def match_stores_from_purchase_data(
    purchase_data: List[Dict[str, Any]],
    route_summary_id: int,
    time_tolerance_minutes: int = 30,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    df = pd.DataFrame(purchase_data)

    purchase_date_candidates = ["仕入れ日", "purchaseDate", "purchase_date"]
    purchase_date_col = next((c for c in purchase_date_candidates if c in df.columns), None)
    if not purchase_date_col:
        raise InventoryStoreMatchingError("仕入れ日カラムが見つかりません")

    supplier_candidates = ["仕入先", "supplier"]
    supplier_col = next((c for c in supplier_candidates if c in df.columns), None)
    if not supplier_col:
        supplier_col = "仕入先"
        df[supplier_col] = ""

    route_db = RouteDatabase(db_path=db_path) if db_path else RouteDatabase()
    route_summary = route_db.get_route_summary(route_summary_id)
    if not route_summary:
        raise InventoryStoreMatchingError("指定ルートが見つかりません")

    store_visits = route_db.get_store_visits_by_route(route_summary_id)
    if not store_visits:
        raise InventoryStoreMatchingError("指定ルートに店舗訪問詳細がありません")

    attach_route_date_to_store_visits(route_summary, store_visits)

    items = df.to_dict(orient="records")
    matcher = RouteMatchingService()
    matched = matcher.match_store_code_by_time_and_profit(
        purchase_items=items,
        store_visits=store_visits,
        time_tolerance_minutes=time_tolerance_minutes,
    )

    df = df.reset_index(drop=True)
    matched_rows = 0
    for idx, res in enumerate(matched):
        code = res.get("matched_store_code")
        if code:
            df.at[idx, supplier_col] = code
            matched_rows += 1

    df = df.fillna("")
    result_data = df.to_dict(orient="records")
    for record in result_data:
        for key, value in record.items():
            if isinstance(value, float) and math.isnan(value):
                record[key] = None

    return {
        "status": "success",
        "stats": {"total_rows": len(df), "matched_rows": matched_rows},
        "data": result_data,
    }
