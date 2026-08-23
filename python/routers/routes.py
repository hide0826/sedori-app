"""ルートサマリー API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.route_db import RouteDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/routes", tags=["routes"])

NON_STORE_CODES = frozenset({"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"})


def _get_db() -> RouteDatabase:
    return RouteDatabase(db_path=get_hirio_db_path_for_api())


def _status_label(row: Dict[str, Any]) -> str:
    flags: List[str] = []
    if row.get("listing_completed"):
        flags.append("出品")
    if row.get("evidence_completed"):
        flags.append("証憑")
    if row.get("images_completed"):
        flags.append("画像")
    if len(flags) == 3:
        return "完了"
    if flags:
        return " / ".join(flags) + " 済"
    return "記録済"


def _format_summary(row: Dict[str, Any], store_count: int) -> Dict[str, Any]:
    display_name = row.get("route_display_name") or row.get("route_code") or ""
    return {
        "id": row["id"],
        "route_date": row.get("route_date"),
        "route_code": row.get("route_code"),
        "route_display_name": display_name,
        "departure_time": row.get("departure_time"),
        "return_time": row.get("return_time"),
        "store_count": store_count,
        "total_item_count": row.get("total_item_count"),
        "total_gross_profit": row.get("total_gross_profit"),
        "estimated_hourly_rate": row.get("estimated_hourly_rate"),
        "listing_completed": bool(row.get("listing_completed")),
        "evidence_completed": bool(row.get("evidence_completed")),
        "images_completed": bool(row.get("images_completed")),
        "status_label": _status_label(row),
        "updated_at": row.get("updated_at"),
    }


def _format_visit(visit: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": visit.get("id"),
        "store_code": visit.get("store_code"),
        "visit_order": visit.get("visit_order"),
        "store_in_time": visit.get("store_in_time"),
        "store_out_time": visit.get("store_out_time"),
        "stay_duration": visit.get("stay_duration"),
        "store_item_count": visit.get("store_item_count"),
        "store_gross_profit": visit.get("store_gross_profit"),
        "store_notes": visit.get("store_notes"),
        "purchase_success": visit.get("purchase_success"),
    }


def _real_store_visits(visits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        v
        for v in visits
        if v.get("store_code") and v.get("store_code") not in NON_STORE_CODES
    ]


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    route_count = 0
    if exists:
        try:
            db = _get_db()
            rows = db.list_route_summaries()
            route_count = len(rows)
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "routes",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "route_count": route_count,
        "error": error,
    }


@router.get("/summaries")
def list_summaries(
    limit: int = Query(50, ge=1, le=200),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    try:
        db = _get_db()
        rows = db.list_route_summaries(start_date=start_date, end_date=end_date)
        summaries: List[Dict[str, Any]] = []
        for row in rows[:limit]:
            visits = db.get_store_visits_by_route(row["id"])
            store_count = len(_real_store_visits(visits))
            summaries.append(_format_summary(row, store_count))
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(summaries),
            "summaries": summaries,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/summaries/{route_id}")
def get_summary(route_id: int):
    try:
        db = _get_db()
        row = db.get_route_summary(route_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"route summary not found: {route_id}")
        visits = db.get_store_visits_by_route(route_id)
        store_count = len(_real_store_visits(visits))
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "summary": _format_summary(row, store_count),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/summaries/{route_id}/visits")
def get_visits(route_id: int):
    try:
        db = _get_db()
        row = db.get_route_summary(route_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"route summary not found: {route_id}")
        visits = db.get_store_visits_by_route(route_id)
        real_visits = _real_store_visits(visits)
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "route_id": route_id,
            "route_date": row.get("route_date"),
            "route_display_name": row.get("route_display_name") or row.get("route_code"),
            "count": len(real_visits),
            "visits": [_format_visit(v) for v in real_visits],
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
