# -*- coding: utf-8 -*-
"""ルート箱の事前処理。レシートはリネームせず、文字だけ読む。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from route_web.desktop_bridge import ensure_desktop_importable

try:
    JST = ZoneInfo("Asia/Tokyo")
except Exception:  # pragma: no cover
    JST = timezone(timedelta(hours=9))

PREP_NAME = "prep_status.json"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


def prep_status_path(folder: Path) -> Path:
    return Path(folder) / PREP_NAME


def load_prep_status(folder: Path) -> Dict[str, Any]:
    path = prep_status_path(folder)
    if not path.is_file():
        return {"status": "idle"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "idle"}
    if not isinstance(data, dict):
        return {"status": "idle"}
    return data


def _write_status(folder: Path, data: Dict[str, Any]) -> None:
    prep_status_path(folder).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _receipt_paths(folder: Path, only_files: Optional[List[str]] = None) -> List[Path]:
    receipt_dir = Path(folder) / "レシート画像"
    if not receipt_dir.is_dir():
        return []
    if only_files:
        names = {Path(name).name for name in only_files}
        return [receipt_dir / name for name in sorted(names) if (receipt_dir / name).is_file()]
    found: List[Path] = []
    for path in sorted(receipt_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
            found.append(path)
    return found


def _registration_number(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None
    match = re.search(r"登録番号[:：]?\s*(T\d{13})", raw_text)
    if not match:
        match = re.search(r"\b(T\d{13})\b", raw_text)
    return match.group(1) if match else None


def parse_receipt_inplace(image_path: Path) -> Dict[str, Any]:
    """既存の process_receipt はファイル名を変えるので、ここでは呼ばない。"""
    ensure_desktop_importable()
    from desktop.services.receipt_service import ReceiptParseResult, ReceiptService

    path = Path(image_path)
    service = ReceiptService()
    parsed = None
    raw_text = ""
    provider = None
    if service.ai_service and service.ai_service.is_available():
        try:
            ai_result = service.ai_service.extract_structured_data(path)
            if ai_result:
                parsed = ReceiptParseResult(
                    purchase_date=ai_result.get("purchase_date"),
                    purchase_time=ai_result.get("purchase_time"),
                    store_name_raw=ai_result.get("store_name_raw"),
                    phone_number=ai_result.get("phone_number"),
                    subtotal=ai_result.get("subtotal"),
                    tax=ai_result.get("tax"),
                    discount_amount=ai_result.get("discount_amount"),
                    total_amount=ai_result.get("total_amount"),
                    paid_amount=ai_result.get("paid_amount"),
                    items_count=ai_result.get("items_count"),
                    plastic_bag_amount=ai_result.get("plastic_bag_amount"),
                )
                raw_text = ai_result.get("raw_text") or ""
                provider = ai_result.get("provider") or "gemini"
        except Exception:
            parsed = None
    if parsed is None:
        ocr = service.ocr.extract_text(str(path), use_preprocessing=True)
        raw_text = ocr.get("text") or ""
        parsed = service.parse_receipt_text(raw_text)
        provider = ocr.get("provider")
    return {
        "purchase_date": parsed.purchase_date,
        "purchase_time": parsed.purchase_time,
        "store_name_raw": parsed.store_name_raw,
        "phone_number": parsed.phone_number,
        "subtotal": parsed.subtotal,
        "tax": parsed.tax,
        "discount_amount": parsed.discount_amount,
        "total_amount": parsed.total_amount,
        "paid_amount": parsed.paid_amount,
        "items_count": parsed.items_count,
        "plastic_bag_amount": parsed.plastic_bag_amount,
        "ocr_provider": provider,
        "ocr_text": raw_text,
        "registration_number": _registration_number(raw_text),
    }


def prepare_route_folder(
    folder: Path,
    *,
    db_path: Optional[str] = None,
    only_files: Optional[List[str]] = None,
    parse_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """CSVの有無を記録し、レシートをその場でOCRする。商品画像は触らない。"""
    ensure_desktop_importable()
    from database.receipt_db import ReceiptDatabase
    from services.route_folder_import import find_stocklist_csv

    folder = Path(folder)
    csv_path = find_stocklist_csv(folder)
    status: Dict[str, Any] = {
        "status": "running",
        "csv_present": csv_path is not None,
        "csv_name": csv_path.name if csv_path else "",
        "started_at": _now(),
        "finished_at": "",
        "receipts": [],
        "error": "",
    }
    _write_status(folder, status)
    db = ReceiptDatabase(db_path)
    parser = parse_fn or parse_receipt_inplace
    try:
        for image in _receipt_paths(folder, only_files):
            resolved = str(image.resolve())
            existing = db.find_by_exact_path(resolved)
            if existing and (str(existing.get("ocr_text") or "").strip() or existing.get("total_amount") is not None):
                status["receipts"].append(
                    {
                        "file": image.name,
                        "skipped": True,
                        "receipt_id": existing.get("id"),
                        "error": "",
                    }
                )
                _write_status(folder, status)
                continue
            try:
                parsed = parser(image)
                before = image.name
                if image.name != before or not image.is_file():
                    raise RuntimeError("レシートファイル名が変わりました")
                receipt_id = db.insert_receipt(
                    {
                        "file_path": resolved,
                        "original_file_path": resolved,
                        "purchase_date": parsed.get("purchase_date"),
                        "purchase_time": parsed.get("purchase_time"),
                        "store_name_raw": parsed.get("store_name_raw"),
                        "phone_number": parsed.get("phone_number"),
                        "store_code": None,
                        "subtotal": parsed.get("subtotal"),
                        "tax": parsed.get("tax"),
                        "discount_amount": parsed.get("discount_amount"),
                        "total_amount": parsed.get("total_amount"),
                        "paid_amount": parsed.get("paid_amount"),
                        "items_count": parsed.get("items_count"),
                        "plastic_bag_amount": parsed.get("plastic_bag_amount"),
                        "currency": "JPY",
                        "ocr_provider": parsed.get("ocr_provider"),
                        "ocr_text": parsed.get("ocr_text") or "",
                        "registration_number": parsed.get("registration_number"),
                    }
                )
                if not image.is_file():
                    raise RuntimeError("OCR後にレシートファイルがありません")
                status["receipts"].append(
                    {
                        "file": image.name,
                        "skipped": False,
                        "receipt_id": receipt_id,
                        "error": "",
                    }
                )
            except Exception as exc:
                status["receipts"].append(
                    {
                        "file": image.name,
                        "skipped": False,
                        "receipt_id": None,
                        "error": str(exc),
                    }
                )
            _write_status(folder, status)
        status["status"] = "done"
    except Exception as exc:
        status["status"] = "error"
        status["error"] = str(exc)
    status["finished_at"] = _now()
    _write_status(folder, status)
    try:
        db.close()
    except Exception:
        pass
    return status
