"""古物台帳 API（hirio.db 読み取り専用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from desktop.database.ledger_db import LedgerDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _get_db() -> LedgerDatabase:
    return LedgerDatabase(db_path=get_hirio_db_path_for_api())


def _format_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    feature_parts = [row.get("kobutsu_kind"), row.get("hinmoku")]
    feature = " / ".join(str(p) for p in feature_parts if p) or ""
    return {
        "id": row.get("id"),
        "entry_date": row.get("entry_date"),
        "hinmei": row.get("hinmei") or "",
        "feature": feature,
        "counterparty_name": row.get("counterparty_name") or "",
        "counterparty_type": row.get("counterparty_type") or "",
        "amount": row.get("amount"),
        "unit_price": row.get("unit_price"),
        "qty": row.get("qty"),
        "sku": row.get("sku") or "",
        "identifier": row.get("identifier") or "",
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
            entry_count = len(db.query_ledger())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "ledger",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "entry_count": entry_count,
        "error": error,
    }


@router.get("/entries")
def list_entries(
    limit: int = Query(50, ge=1, le=200),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    try:
        db = _get_db()
        where_parts: List[str] = []
        params: List[Any] = []
        if start_date:
            where_parts.append("entry_date >= ?")
            params.append(start_date)
        if end_date:
            where_parts.append("entry_date <= ?")
            params.append(end_date)
        where = " AND ".join(where_parts) if where_parts else ""
        rows = db.query_ledger(where, tuple(params))
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
