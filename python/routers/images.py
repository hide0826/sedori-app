"""画像管理 API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.image_db import ImageDatabase
from desktop.database.product_db import ProductDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/images", tags=["images"])

_IMAGE_PATH_KEYS = [f"image_{i}" for i in range(1, 7)]
_IMAGE_URL_KEYS = [f"image_url_{i}" for i in range(1, 7)]


def _get_product_db() -> ProductDatabase:
    return ProductDatabase(db_path=get_hirio_db_path_for_api())


def _get_image_db() -> ImageDatabase:
    return ImageDatabase(db_path=get_hirio_db_path_for_api())


def _count_images(row: Dict[str, Any]) -> int:
    return sum(1 for key in _IMAGE_PATH_KEYS if row.get(key))


def _has_urls(row: Dict[str, Any]) -> bool:
    return any(row.get(key) for key in _IMAGE_URL_KEYS)


def _format_product_images(row: Dict[str, Any]) -> Dict[str, Any]:
    image_count = _count_images(row)
    has_urls = _has_urls(row)
    if image_count > 0:
        status = "登録済"
    elif has_urls:
        status = "URLのみ"
    else:
        status = "未登録"
    return {
        "sku": row.get("sku") or "",
        "product_name": row.get("product_name") or "",
        "jan": row.get("jan") or "",
        "image_count": image_count,
        "has_urls": has_urls,
        "status": status,
    }


def _format_scanned(row: Dict[str, Any]) -> Dict[str, Any]:
    file_path = row.get("file_path") or ""
    return {
        "id": row.get("id"),
        "jan": row.get("jan") or "",
        "file_name": Path(file_path).name if file_path else "",
        "file_path": file_path,
        "capture_time": row.get("capture_time"),
        "group_index": row.get("group_index"),
        "rotation": row.get("rotation") or 0,
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    product_count = 0
    scanned_count = 0
    if exists:
        try:
            product_db = _get_product_db()
            image_db = _get_image_db()
            product_count = len(product_db.list_all())
            scanned_count = len(image_db.list_all())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "images",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "product_count": product_count,
        "scanned_count": scanned_count,
        "error": error,
    }


@router.get("/products")
def list_product_images(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="未登録 / 登録済 / URLのみ"),
):
    try:
        db = _get_product_db()
        rows = db.list_all()
        items = [_format_product_images(row) for row in rows]
        if status:
            items = [item for item in items if item["status"] == status]
        limited = items[:limit]
        registered = sum(1 for item in items if item["status"] == "登録済")
        unregistered = sum(1 for item in items if item["status"] == "未登録")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(limited),
            "total": len(items),
            "registered_count": registered,
            "unregistered_count": unregistered,
            "items": limited,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/scanned")
def list_scanned_images(
    limit: int = Query(50, ge=1, le=200),
):
    try:
        db = _get_image_db()
        rows = db.list_all(order_by="capture_time DESC, id DESC")
        items = [_format_scanned(row) for row in rows[:limit]]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(items),
            "total": len(rows),
            "items": items,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
