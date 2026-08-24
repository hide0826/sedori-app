"""勘定科目 API（hirio.db 読み書き）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from desktop.database.account_title_db import AccountTitleDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/account-titles", tags=["account-titles"])


class DebitTitlePayload(BaseModel):
    name: str = Field(..., min_length=1)
    note: str = ""


class CreditAccountPayload(BaseModel):
    name: str = Field(..., min_length=1)
    card_name: str = ""
    last_four_digits: str = ""
    is_default: bool = False
    note: str = ""


class CreditAccountUpdatePayload(BaseModel):
    name: Optional[str] = None
    card_name: Optional[str] = None
    last_four_digits: Optional[str] = None
    is_default: Optional[bool] = None
    note: Optional[str] = None


def _get_db() -> AccountTitleDatabase:
    return AccountTitleDatabase(db_path=get_hirio_db_path_for_api())


def _format_debit(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name") or "",
        "sort_order": row.get("sort_order") or 0,
        "note": row.get("note") or "",
        "type": "借方",
    }


def _format_credit(row: Dict[str, Any]) -> Dict[str, Any]:
    card = row.get("card_name") or ""
    last4 = row.get("last_four_digits") or ""
    label = row.get("name") or ""
    if card and last4:
        label = f"{label} ({card} ****{last4})"
    elif card:
        label = f"{label} ({card})"
    return {
        "id": row.get("id"),
        "name": label,
        "raw_name": row.get("name") or "",
        "card_name": card,
        "last_four_digits": last4,
        "is_default": bool(row.get("is_default")),
        "sort_order": row.get("sort_order") or 0,
        "note": row.get("note") or "",
        "type": "貸方",
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    debit_count = 0
    credit_count = 0
    if exists:
        try:
            db = _get_db()
            debit_count = len(db.list_titles())
            credit_count = len(db.list_credit_accounts())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "account-titles",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "debit_count": debit_count,
        "credit_count": credit_count,
        "error": error,
        "writable": True,
    }


@router.get("/debit")
def list_debit_titles():
    try:
        db = _get_db()
        rows = db.list_titles()
        titles = [_format_debit(row) for row in rows]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(titles),
            "total": len(titles),
            "titles": titles,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/debit")
def create_debit_title(body: DebitTitlePayload):
    try:
        db = _get_db()
        new_id = db.add_title(body.name, body.note)
        rows = db.list_titles()
        row = next((r for r in rows if r.get("id") == new_id), None)
        if not row:
            # INSERT OR IGNORE で既存の場合 lastrowid が 0 のことがある
            row = next((r for r in rows if (r.get("name") or "") == body.name.strip()), None)
        if not row:
            raise HTTPException(status_code=400, detail="科目の追加に失敗しました（同名の可能性）")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "title": _format_debit(row),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/debit/{title_id}")
def delete_debit_title(title_id: int):
    try:
        db = _get_db()
        ok = db.delete_title(title_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"借方科目 id={title_id} が見つかりません")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "deleted_id": title_id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/credit")
def list_credit_accounts():
    try:
        db = _get_db()
        rows = db.list_credit_accounts()
        accounts = [_format_credit(row) for row in rows]
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(accounts),
            "total": len(accounts),
            "accounts": accounts,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/credit")
def create_credit_account(body: CreditAccountPayload):
    try:
        db = _get_db()
        new_id = db.add_credit_account(
            body.name,
            card_name=body.card_name,
            last_four_digits=body.last_four_digits,
            is_default=body.is_default,
            note=body.note,
        )
        rows = db.list_credit_accounts()
        row = next((r for r in rows if r.get("id") == new_id), None)
        if not row:
            raise HTTPException(status_code=500, detail="貸方科目の追加後の取得に失敗しました")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "account": _format_credit(row),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/credit/{account_id}")
def update_credit_account(account_id: int, body: CreditAccountUpdatePayload):
    try:
        db = _get_db()
        rows = db.list_credit_accounts()
        existing = next((r for r in rows if r.get("id") == account_id), None)
        if not existing:
            raise HTTPException(status_code=404, detail=f"貸方科目 id={account_id} が見つかりません")
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="更新する項目がありません")
        ok = db.update_credit_account(account_id, **data)
        if not ok:
            raise HTTPException(status_code=500, detail="更新に失敗しました")
        rows = db.list_credit_accounts()
        row = next((r for r in rows if r.get("id") == account_id), existing)
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "account": _format_credit(row),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/credit/{account_id}")
def delete_credit_account(account_id: int):
    try:
        db = _get_db()
        ok = db.delete_credit_account(account_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"貸方科目 id={account_id} が見つかりません")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "deleted_id": account_id,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
