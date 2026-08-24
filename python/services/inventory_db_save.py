"""仕入データの DB 保存（デスクトップ InventoryWidget.save_to_databases の第一弾）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from desktop.database.product_purchase_db import ProductPurchaseDatabase
from desktop.database.route_db import RouteDatabase
from desktop.database.route_visit_db import RouteVisitDatabase
from desktop.database.store_db import StoreDatabase
from utils.server_db_paths import (
    get_hirio_db_path_for_api,
    get_product_purchase_db_path_for_api,
)

NON_STORE_CODES = frozenset({"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"})


def _normalize_datetime_for_match(date_str: str) -> str:
    s = str(date_str or "").strip().replace("/", "-").replace(".", "-")
    date_part = s
    time_part = ""
    if " " in s:
        date_part, time_part = s.split(" ", 1)
        time_part = time_part.strip()
        if time_part and ":" in time_part:
            t_parts = time_part.split(":")
            if len(t_parts) >= 2:
                try:
                    time_part = f"{int(t_parts[0]):02d}:{int(t_parts[1]):02d}"
                except (ValueError, IndexError):
                    time_part = ""
    d_parts = date_part.split("-")
    if len(d_parts) >= 3:
        try:
            date_part = f"{int(d_parts[0]):04d}-{int(d_parts[1]):02d}-{int(d_parts[2]):02d}"
        except (ValueError, IndexError):
            pass
    if time_part:
        return f"{date_part} {time_part}"
    return date_part


def _datetime_asin_key(record: Dict[str, Any]) -> Optional[str]:
    purchase_datetime = _normalize_datetime_for_match(
        str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
    )
    asin = str(record.get("ASIN") or record.get("asin") or "").strip()
    if not purchase_datetime or not asin:
        return None
    return f"DT_ASIN:{purchase_datetime}|{asin.upper()}"


def _purchase_record_key(record: Dict[str, Any]) -> Optional[str]:
    sku = str(record.get("SKU") or record.get("sku") or "").strip()
    if sku:
        return f"SKU:{sku}"
    purchase_date = str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
    asin = str(record.get("ASIN") or record.get("asin") or "").strip()
    jan = str(record.get("JAN") or record.get("jan") or "").strip()
    title = str(
        record.get("商品名") or record.get("title") or record.get("product_name") or ""
    ).strip()
    store_code = str(
        record.get("仕入先") or record.get("店舗コード") or record.get("store_code") or ""
    ).strip()
    asin_or_jan = asin or jan
    if not (purchase_date or asin_or_jan or title or store_code):
        return None
    return f"NO-SKU:{purchase_date}|{asin_or_jan}|{store_code}|{title}"


def merge_purchase_snapshots(
    incoming: List[Dict[str, Any]],
    existing: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    existing_all = list(existing)
    existing_datetime_asin: set = set()
    existing_index: Dict[str, int] = {}
    for idx, rec in enumerate(existing_all):
        dt_key = _datetime_asin_key(rec)
        if dt_key:
            existing_datetime_asin.add(dt_key)
        key = _purchase_record_key(rec)
        if key:
            existing_index[key] = idx

    updated_count = 0
    new_count = 0
    skipped_count = 0

    for record in incoming:
        dt_key = _datetime_asin_key(record)
        if dt_key and dt_key in existing_datetime_asin:
            skipped_count += 1
            continue
        key = _purchase_record_key(record)
        if key and key in existing_index:
            existing_rec = existing_all[existing_index[key]]
            new_sku = str(record.get("SKU") or record.get("sku") or "").strip()
            existing_sku = str(existing_rec.get("SKU") or existing_rec.get("sku") or "").strip()
            if new_sku.endswith("...") and existing_sku and not existing_sku.endswith("..."):
                record = dict(record)
                record["SKU"] = existing_sku
                record["sku"] = existing_sku
            existing_all[existing_index[key]] = record
            updated_count += 1
        else:
            existing_all.append(record)
            if key:
                existing_index[key] = len(existing_all) - 1
            if dt_key:
                existing_datetime_asin.add(dt_key)
            new_count += 1

    return existing_all, {
        "new_count": new_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "total_count": len(existing_all),
    }


def save_purchase_data(purchase_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not purchase_data:
        return {
            "saved": False,
            "message": "仕入データ: データがありません",
            "stats": {"new_count": 0, "updated_count": 0, "skipped_count": 0, "total_count": 0},
            "db_path": get_product_purchase_db_path_for_api(),
        }

    db = ProductPurchaseDatabase(db_path=get_product_purchase_db_path_for_api())
    existing: List[Dict[str, Any]] = []
    snapshots = db.list_snapshots()
    if snapshots:
        latest = db.get_snapshot(snapshots[0]["id"])
        if latest:
            existing = latest.get("data") or []

    merged, stats = merge_purchase_snapshots(purchase_data, existing)
    db.save_snapshot("自動保存(仕入DB)", merged)

    parts = [f"{stats['new_count']}件の新規データを追加"]
    if stats["updated_count"]:
        parts.append(f"{stats['updated_count']}件を更新")
    if stats["skipped_count"]:
        parts.append(f"{stats['skipped_count']}件をスキップ（同一仕入時間・ASINの既存あり）")
    message = (
        "仕入データ: "
        + "、".join(parts)
        + f"しました。（合計: {stats['total_count']}件）"
    )
    return {
        "saved": True,
        "message": message,
        "stats": stats,
        "db_path": db.db_path,
    }


def load_route_template(route_summary_id: int) -> Dict[str, Any]:
    db_path = get_hirio_db_path_for_api()
    route_db = RouteDatabase(db_path=db_path)
    store_db = StoreDatabase(db_path=db_path)
    row = route_db.get_route_summary(route_summary_id)
    if not row:
        raise ValueError(f"ルートが見つかりません: {route_summary_id}")

    raw_visits = route_db.get_store_visits_by_route(route_summary_id)
    visits: List[Dict[str, Any]] = []
    for visit in raw_visits:
        store_code = visit.get("store_code") or ""
        if store_code in NON_STORE_CODES:
            continue
        store_name = visit.get("store_name") or ""
        if not store_name and store_code:
            store_info = store_db.get_store_by_code(store_code)
            if store_info:
                store_name = store_info.get("store_name") or ""
        visits.append(
            {
                "id": visit.get("id"),
                "visit_order": visit.get("visit_order"),
                "store_code": store_code,
                "store_name": store_name,
                "store_in_time": visit.get("store_in_time"),
                "store_out_time": visit.get("store_out_time"),
                "stay_duration": visit.get("stay_duration"),
                "travel_time_from_prev": visit.get("travel_time_from_prev"),
                "store_gross_profit": visit.get("store_gross_profit"),
                "store_item_count": visit.get("store_item_count"),
                "store_rating": visit.get("store_rating"),
                "store_notes": visit.get("store_notes"),
            }
        )

    display_name = row.get("route_display_name") or row.get("route_code") or ""
    return {
        "source": "server_db",
        "db_path": db_path,
        "summary": {
            "id": row["id"],
            "route_date": row.get("route_date"),
            "route_code": row.get("route_code"),
            "route_display_name": display_name,
            "departure_time": row.get("departure_time"),
            "return_time": row.get("return_time"),
        },
        "count": len(visits),
        "visits": visits,
    }


def save_route_visits_from_summary(route_summary_id: int) -> Dict[str, Any]:
    template = load_route_template(route_summary_id)
    summary = template["summary"]
    visits = template["visits"]
    route_date = summary.get("route_date") or ""
    route_code = summary.get("route_code") or ""
    route_name = summary.get("route_display_name") or route_code

    if not route_date or not route_code or not visits:
        return {
            "saved": False,
            "message": "ルート情報: ルートデータが不完全です（日付・ルートコード・訪問データが必要）",
        }

    visit_db = RouteVisitDatabase(db_path=get_hirio_db_path_for_api())
    existing = visit_db.list_route_visits(route_date=route_date, route_code=route_code)
    visit_db.replace_route_visits(route_date, route_code, route_name, visits)
    if existing:
        message = f"ルート情報 ({route_date} {route_name}): {len(visits)}件を保存しました"
    else:
        message = f"ルート情報 ({route_date} {route_name}): {len(visits)}件を保存しました"
    return {"saved": True, "message": message, "visit_count": len(visits)}
