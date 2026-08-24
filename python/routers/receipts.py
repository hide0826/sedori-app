"""レシート・領収書 API（読み取り＋手動編集。OCRパイプラインはデスクトップが正）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from desktop.database.receipt_db import ReceiptDatabase
from utils.server_db_paths import get_hirio_db_path_for_api

router = APIRouter(prefix="/api/receipts", tags=["receipts"])

# デスクトップ編集ダイアログで保存される項目
_EDITABLE_KEYS = (
    "account_title",
    "purchase_date",
    "purchase_time",
    "store_code",
    "store_name_raw",
    "phone_number",
    "registration_number",
    "total_amount",
    "discount_amount",
    "linked_skus",
    "price_difference",
)


class ReceiptUpdatePayload(BaseModel):
    account_title: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_time: Optional[str] = None
    store_code: Optional[str] = None
    store_name: Optional[str] = Field(None, description="店舗名（store_name_raw）")
    phone_number: Optional[str] = None
    registration_number: Optional[str] = None
    total_amount: Optional[int] = None
    discount_amount: Optional[int] = None
    linked_skus: Optional[str] = None
    price_difference: Optional[int] = None


def _get_db() -> ReceiptDatabase:
    return ReceiptDatabase(db_path=get_hirio_db_path_for_api())


def _fix_mojibake(text: str) -> str:
    """UTF-8 を Latin-1 として読んだ文字化けを修復（典型: æ¬²æµµ…）。"""
    if not text:
        return text
    # 日本語として自然な文字列ならそのまま
    if any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    markers = ("æ", "å", "ç", "ø", "ð")
    if not any(m in text for m in markers):
        return text
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in fixed):
        return fixed
    return text


def _doc_type(row: Dict[str, Any]) -> str:
    ocr = str(row.get("ocr_text") or "")
    if "保証書" in ocr or "保証期間" in ocr or "保証規定" in ocr:
        return "保証書"
    if row.get("warranty_days") or row.get("warranty_until") or row.get("sku"):
        return "保証書"
    return "レシート"


def _match_status(row: Dict[str, Any]) -> str:
    linked = (row.get("linked_skus") or "").strip()
    return "突合済" if linked else "未突合"


def _format_receipt(row: Dict[str, Any]) -> Dict[str, Any]:
    file_path = row.get("file_path") or ""
    return {
        "id": row.get("id"),
        "purchase_date": row.get("purchase_date"),
        "purchase_time": row.get("purchase_time") or "",
        "store_name": _fix_mojibake(row.get("store_name_raw") or ""),
        "store_code": row.get("store_code") or "",
        "phone_number": row.get("phone_number") or "",
        "registration_number": row.get("registration_number") or "",
        "total_amount": row.get("total_amount"),
        "discount_amount": row.get("discount_amount"),
        "price_difference": row.get("price_difference"),
        "linked_skus": row.get("linked_skus") or "",
        "match_status": _match_status(row),
        "account_title": _fix_mojibake(row.get("account_title") or ""),
        "gcs_url": row.get("gcs_url") or "",
        "file_name": Path(file_path).name if file_path else "",
        "doc_type": _doc_type(row),
        "sku": row.get("sku") or "",
        "product_name": _fix_mojibake(row.get("product_name") or ""),
        "warranty_days": row.get("warranty_days"),
        "warranty_until": row.get("warranty_until") or "",
    }


@router.get("/health")
def health_check():
    db_path = get_hirio_db_path_for_api()
    exists = Path(db_path).exists()
    readable = False
    error: Optional[str] = None
    receipt_count = 0
    unmatched_count = 0
    if exists:
        try:
            db = _get_db()
            rows = db.find_by_date_and_store(None)
            receipt_count = len(rows)
            unmatched_count = sum(1 for row in rows if not (row.get("linked_skus") or "").strip())
            readable = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
    return {
        "status": "ok" if readable else ("missing_db" if not exists else "error"),
        "service": "receipts",
        "db_path": db_path,
        "db_exists": exists,
        "db_readable": readable,
        "receipt_count": receipt_count,
        "unmatched_count": unmatched_count,
        "error": error,
        "writable": True,
        "note": "手動編集のみ。OCR・一括マッチ・GCS・確定はデスクトップ",
    }


@router.get("")
def list_receipts(
    limit: int = Query(100, ge=1, le=500),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    store_code: Optional[str] = None,
):
    try:
        db = _get_db()
        rows = db.find_by_date_and_store(None, store_code=store_code)
        if start_date:
            rows = [row for row in rows if (row.get("purchase_date") or "") >= start_date]
        if end_date:
            rows = [row for row in rows if (row.get("purchase_date") or "") <= end_date]
        receipts = [_format_receipt(row) for row in rows[:limit]]
        unmatched = sum(1 for row in rows if _match_status(row) == "未突合")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "count": len(receipts),
            "total": len(rows),
            "unmatched_count": unmatched,
            "receipts": receipts,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{receipt_id}")
def get_receipt(receipt_id: int):
    try:
        db = _get_db()
        row = db.get_receipt(receipt_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"レシート id={receipt_id} が見つかりません")
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "receipt": _format_receipt(row),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/{receipt_id}")
def update_receipt(receipt_id: int, body: ReceiptUpdatePayload):
    """デスクトップ編集ダイアログ相当の手動更新。"""
    try:
        db = _get_db()
        existing = db.get_receipt(receipt_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"レシート id={receipt_id} が見つかりません")

        updates: Dict[str, Any] = {}
        raw = body.model_dump(exclude_unset=True)
        if "store_name" in raw:
            updates["store_name_raw"] = _fix_mojibake(str(raw.pop("store_name") or ""))
        for key, value in raw.items():
            if key in _EDITABLE_KEYS or key == "store_name_raw":
                if isinstance(value, str) and key in (
                    "account_title",
                    "store_name_raw",
                    "store_code",
                ):
                    updates[key] = _fix_mojibake(value)
                else:
                    updates[key] = value

        # デスクトップ: 科目が「仕入」以外なら SKU 紐付けをクリア
        title = updates.get("account_title")
        if title is None:
            title = existing.get("account_title") or ""
        if str(title).strip() != "仕入":
            if "linked_skus" not in updates:
                updates["linked_skus"] = ""
            if "price_difference" not in updates:
                updates["price_difference"] = 0

        if not updates:
            raise HTTPException(status_code=400, detail="更新する項目がありません")

        ok = db.update_receipt(receipt_id, updates)
        if not ok:
            raise HTTPException(status_code=500, detail="更新に失敗しました")
        row = db.get_receipt(receipt_id)
        return {
            "source": "server_db",
            "db_path": db.db_path,
            "receipt": _format_receipt(row or existing),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
