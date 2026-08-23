"""分析 API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.product_db import ProductDatabase
from desktop.database.route_visit_db import RouteVisitDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _get_products_db() -> ProductDatabase:
    return ProductDatabase(db_path=get_hirio_db_path_for_api())


def _get_visits_db() -> RouteVisitDatabase:
    return RouteVisitDatabase(db_path=get_hirio_db_path_for_api())


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    if exists:
        try:
            _get_products_db().list_all()
            _get_visits_db().get_store_visit_aggregates()
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "analysis",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "error": error,
    }


@router.get("/summary")
def basic_summary(days: int = Query(30, ge=1, le=365)):
    try:
        from datetime import date, timedelta

        product_db = _get_products_db()
        products = product_db.list_all()

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        recent = [
            p
            for p in products
            if (p.get("purchase_date") or "") >= cutoff
        ]

        total_qty = sum(int(p.get("quantity") or 1) for p in recent)
        total_amount = sum(
            int(p.get("purchase_price") or 0) * int(p.get("quantity") or 1)
            for p in recent
        )
        avg_price = round(total_amount / total_qty, 0) if total_qty else 0
        store_codes = {
            str(p.get("store_code") or "").strip()
            for p in recent
            if str(p.get("store_code") or "").strip()
        }

        metrics = [
            {
                "metric": "仕入件数",
                "value": len(recent),
                "note": f"直近{days}日",
            },
            {
                "metric": "仕入点数",
                "value": total_qty,
                "note": f"直近{days}日",
            },
            {
                "metric": "仕入総額",
                "value": total_amount,
                "note": "円（税込想定）",
            },
            {
                "metric": "平均仕入単価",
                "value": int(avg_price),
                "note": "1点あたり",
            },
        ]

        return {
            "source": "server_db",
            "db_path": product_db.db_path,
            "days": days,
            "store_count": len(store_codes),
            "metrics": metrics,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/store-scores")
def store_scores(limit: int = Query(30, ge=1, le=200)):
    try:
        visit_db = _get_visits_db()
        rows = visit_db.get_store_visit_aggregates()
        rows.sort(
            key=lambda r: float(r.get("total_gross_profit") or 0),
            reverse=True,
        )

        scores: List[Dict[str, Any]] = []
        for row in rows[:limit]:
            visit_count = int(row.get("visit_count") or 0)
            avg_rating = float(row.get("avg_rating") or 0)
            gross = float(row.get("total_gross_profit") or 0)
            if avg_rating > 0:
                score = int(round(avg_rating * 20))
            else:
                score = min(99, 40 + visit_count * 3)
            hourly = int(gross / visit_count) if visit_count else 0
            scores.append(
                {
                    "store_code": row.get("store_code") or "",
                    "store_name": row.get("store_name") or row.get("store_code") or "",
                    "score": score,
                    "hourly_estimate": hourly,
                    "visit_count": visit_count,
                    "total_gross_profit": gross,
                    "avg_rating": avg_rating,
                    "trend": "—",
                }
            )

        return {
            "source": "server_db",
            "db_path": visit_db.db_path,
            "count": len(scores),
            "total": len(rows),
            "stores": scores,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
