"""仕訳帳 API（hirio.db 読み書き・デスクトップ JournalEntryWidget 踏襲）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from desktop.database.journal_db import JournalDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/journal", tags=["journal"])


class JournalPayload(BaseModel):
    transaction_date: str = Field(..., min_length=1)
    debit_account: str = Field(..., min_length=1)
    amount: int = Field(..., ge=0)
    credit_account: str = Field(..., min_length=1)
    description: str = ""
    invoice_number: str = ""
    tax_category: str = ""
    image_url: str = ""


def _get_db() -> JournalDatabase:
    return JournalDatabase(db_path=get_hirio_db_path_for_api())


def _format_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "transaction_date": row.get("transaction_date"),
        "debit_account": row.get("debit_account") or "",
        "amount": row.get("amount"),
        "credit_account": row.get("credit_account") or "",
        "description": row.get("description") or "",
        "invoice_number": row.get("invoice_number") or "",
        "tax_category": row.get("tax_category") or "",
        "image_url": row.get("image_url") or "",
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    entry_count = 0
    if exists:
        try:
            db = _get_db()
            entry_count = len(db.list_all())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "journal",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "entry_count": entry_count,
        "error": error,
        "writable": True,
    }


@router.get("/entries")
def list_entries(
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
        entries = [_format_entry(row) for row in rows[:limit]]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(entries),
            "total": len(rows),
            "entries": entries,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/entries")
def create_entry(body: JournalPayload):
    try:
        db = _get_db()
        new_id = db.insert(body.model_dump())
        row = db.get_by_id(new_id)
        if not row:
            raise HTTPException(status_code=500, detail="保存後の取得に失敗しました")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "entry": _format_entry(row),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/entries/{entry_id}")
def update_entry(entry_id: int, body: JournalPayload):
    try:
        db = _get_db()
        existing = db.get_by_id(entry_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"仕訳 id={entry_id} が見つかりません")
        ok = db.update(entry_id, body.model_dump())
        if not ok:
            raise HTTPException(status_code=500, detail="更新に失敗しました")
        row = db.get_by_id(entry_id)
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "entry": _format_entry(row or existing),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int):
    try:
        db = _get_db()
        existing = db.get_by_id(entry_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"仕訳 id={entry_id} が見つかりません")
        ok = db.delete(entry_id)
        if not ok:
            raise HTTPException(status_code=500, detail="削除に失敗しました")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "deleted_id": entry_id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
