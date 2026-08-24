"""経費管理 API（hirio.db 読み書き・デスクトップ ExpenseWidget 踏襲）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from desktop.database.expense_db import ExpenseDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/expenses", tags=["expenses"])

EXPENSE_CATEGORIES: List[str] = [
    "消耗品費",
    "旅費交通費",
    "通信費",
    "光熱費",
    "広告宣伝費",
    "その他",
]

PAYMENT_METHODS: List[str] = [
    "現金",
    "クレジットカード",
    "QR決済",
    "電子マネー",
    "その他",
]


class ExpensePayload(BaseModel):
    id: Optional[int] = None
    expense_date: str = Field(..., min_length=1)
    expense_category: str = Field(..., min_length=1)
    account_title: str = ""
    store_name: str = ""
    store_code: str = ""
    amount: int = Field(..., ge=0)
    quantity: int = Field(1, ge=1, le=9999)
    unit_price: Optional[int] = Field(None, ge=0)
    payment_method: str = ""
    receipt_id: Optional[int] = None
    receipt_file_path: str = ""
    memo: str = ""


def _get_db() -> ExpenseDatabase:
    return ExpenseDatabase(db_path=get_hirio_db_path_for_api())


def _format_expense(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "expense_date": row.get("expense_date"),
        "expense_category": row.get("expense_category") or "",
        "account_title": row.get("account_title") or "",
        "store_name": row.get("store_name") or "",
        "store_code": row.get("store_code") or "",
        "amount": row.get("amount"),
        "quantity": row.get("quantity") if row.get("quantity") is not None else 1,
        "unit_price": row.get("unit_price"),
        "payment_method": row.get("payment_method") or "",
        "receipt_id": row.get("receipt_id"),
        "receipt_file_path": row.get("receipt_file_path") or "",
        "memo": row.get("memo") or "",
    }


def _normalize_payload(body: ExpensePayload) -> Dict[str, Any]:
    data = body.model_dump()
    # デスクトップ: 勘定科目が空ならカテゴリをコピー
    if not (data.get("account_title") or "").strip():
        data["account_title"] = data.get("expense_category") or ""
    # デスクトップ: 単価 0 は None
    if data.get("unit_price") == 0:
        data["unit_price"] = None
    return data


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    expense_count = 0
    if exists:
        try:
            db = _get_db()
            expense_count = len(db.list_all())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "expenses",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "expense_count": expense_count,
        "error": error,
        "writable": True,
        "categories": EXPENSE_CATEGORIES,
        "payment_methods": PAYMENT_METHODS,
    }


@router.get("")
def list_expenses(
    limit: int = Query(100, ge=1, le=500),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    try:
        db = _get_db()
        if start_date or end_date:
            rows = db.list_by_date(start_date=start_date, end_date=end_date)
        else:
            rows = db.list_all()
        expenses = [_format_expense(row) for row in rows[:limit]]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(expenses),
            "total": len(rows),
            "expenses": expenses,
            "categories": EXPENSE_CATEGORIES,
            "payment_methods": PAYMENT_METHODS,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("")
def create_expense(body: ExpensePayload):
    try:
        db = _get_db()
        payload = _normalize_payload(body)
        payload.pop("id", None)
        new_id = db.upsert(payload)
        row = db.get_by_id(new_id)
        if not row:
            raise HTTPException(status_code=500, detail="保存後の取得に失敗しました")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "expense": _format_expense(row),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/{expense_id}")
def update_expense(expense_id: int, body: ExpensePayload):
    try:
        db = _get_db()
        existing = db.get_by_id(expense_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"経費 id={expense_id} が見つかりません")
        payload = _normalize_payload(body)
        payload["id"] = expense_id
        db.upsert(payload)
        row = db.get_by_id(expense_id)
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "expense": _format_expense(row or existing),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{expense_id}")
def delete_expense(expense_id: int):
    try:
        db = _get_db()
        existing = db.get_by_id(expense_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"経費 id={expense_id} が見つかりません")
        ok = db.delete(expense_id)
        if not ok:
            raise HTTPException(status_code=500, detail="削除に失敗しました")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "deleted_id": expense_id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
