"""ルート訪問DB API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.route_visit_db import RouteVisitDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/route-visits", tags=["route-visits"])


def _get_db() -> RouteVisitDatabase:
    return RouteVisitDatabase(db_path=get_hirio_db_path_for_api())


def _format_visit(row: Dict[str, Any]) -> Dict[str, Any]:
    stay = row.get("stay_duration")
    return {
        "route_date": row.get("route_date"),
        "route_code": row.get("route_code"),
        "route_name": row.get("route_name"),
        "store_code": row.get("store_code"),
        "store_name": row.get("store_name"),
        "store_in_time": row.get("store_in_time"),
        "store_out_time": row.get("store_out_time"),
        "stay_duration_minutes": round(stay, 1) if stay is not None else None,
        "store_item_count": row.get("store_item_count"),
        "store_gross_profit": row.get("store_gross_profit"),
        "store_rating": row.get("store_rating"),
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    visit_count = 0
    if exists:
        try:
            db = _get_db()
            visit_count = len(db.list_route_visits())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "route-visits",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "visit_count": visit_count,
        "error": error,
    }


@router.get("")
def list_visits(
    limit: int = Query(100, ge=1, le=500),
    route_date: Optional[str] = None,
    route_code: Optional[str] = None,
):
    try:
        db = _get_db()
        rows = db.list_route_visits(route_date=route_date, route_code=route_code)
        visits = [_format_visit(row) for row in rows[:limit]]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(visits),
            "total": len(rows),
            "visits": visits,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
