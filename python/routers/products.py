"""商品DB API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.product_db import ProductDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/products", tags=["products"])


def _get_db() -> ProductDatabase:
    return ProductDatabase(db_path=get_hirio_db_path_for_api())


def _format_product(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sku": row.get("sku") or "",
        "jan": row.get("jan") or "",
        "asin": row.get("asin") or "",
        "product_name": row.get("product_name") or "",
        "purchase_date": row.get("purchase_date"),
        "purchase_price": row.get("purchase_price"),
        "quantity": row.get("quantity"),
        "store_code": row.get("store_code") or "",
        "store_name": row.get("store_name") or "",
        "listed_date": row.get("listed_date"),
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    product_count = 0
    if exists:
        try:
            db = _get_db()
            product_count = len(db.list_all())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "products",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "product_count": product_count,
        "error": error,
    }


@router.get("")
def list_products(
    limit: int = Query(50, ge=1, le=200),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    try:
        db = _get_db()
        if start_date or end_date:
            rows = db.list_by_date(start_date=start_date, end_date=end_date)
        else:
            rows = db.list_all()
        products = [_format_product(row) for row in rows[:limit]]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(products),
            "total": len(rows),
            "products": products,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
