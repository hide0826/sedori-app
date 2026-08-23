"""店舗マスタ API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.store_db import StoreDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/stores", tags=["stores"])


def _get_db() -> StoreDatabase:
    return StoreDatabase(db_path=get_hirio_db_path_for_api())


def _format_store(row: Dict[str, Any]) -> Dict[str, Any]:
    code = row.get("store_code") or row.get("supplier_code") or ""
    return {
        "id": row.get("id"),
        "store_code": code,
        "store_name": row.get("store_name") or "",
        "route_code": row.get("route_code") or "",
        "affiliated_route_name": row.get("affiliated_route_name") or "",
        "address": row.get("address") or "",
        "phone": row.get("phone") or "",
        "display_order": row.get("display_order"),
        "template_include": bool(row.get("template_include", 1)),
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    store_count = 0
    if exists:
        try:
            db = _get_db()
            store_count = len(db.list_stores())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "stores",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "store_count": store_count,
        "error": error,
    }


@router.get("")
def list_stores(
    q: Optional[str] = Query(None, description="店舗名・コード・ルート名の部分一致"),
    limit: int = Query(200, ge=1, le=500),
):
    try:
        db = _get_db()
        rows = db.list_stores(search_term=q.strip() if q else None)
        stores = [_format_store(row) for row in rows[:limit]]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(stores),
            "total": len(rows),
            "stores": stores,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
