#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシート ↔ 仕入DB SKU 紐付けの共通ロジック

- 一括マッチング: レシート時刻順・同一店舗は早いレシートから・使用済みSKUは除外
- 手動調整候補: 店舗コード一致 → 同日 の順で表示
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)


def normalize_store_code(code: Any) -> str:
    text = str(code or "").strip()
    if " " in text:
        text = text.split(" ")[0]
    return text


def parse_date_only(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    if " " in text:
        text = text.split(" ")[0]
    if "T" in text:
        text = text.split("T")[0]
    text = text.replace("/", "-")
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_datetime_text(text: str) -> Optional[datetime]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1]
    normalized = cleaned.replace("/", "-")
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    if "T" in normalized and len(normalized) >= 19:
        try:
            return datetime.strptime(normalized[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    if " " in normalized and len(normalized) >= 19:
        try:
            return datetime.strptime(normalized[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def parse_purchase_record_datetime(record: Dict[str, Any]) -> Optional[datetime]:
    """仕入DBレコードの仕入日時を datetime に変換"""
    for key in ("仕入れ日", "purchase_date", "日付/時間", "日付/時刻"):
        dt = _parse_datetime_text(str(record.get(key) or ""))
        if dt:
            return dt

    record_date = parse_date_only(record.get("仕入れ日") or record.get("purchase_date"))
    record_time = str(record.get("仕入れ時刻") or record.get("purchase_time") or "").strip()
    if record_date and record_time:
        try:
            parts = record_time.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            return datetime(record_date.year, record_date.month, record_date.day, hour, minute)
        except (ValueError, IndexError):
            pass

    for key in ("created_at", "登録日時"):
        dt = _parse_datetime_text(str(record.get(key) or ""))
        if dt:
            return dt
    return None


def parse_receipt_datetime(receipt: Dict[str, Any]) -> Optional[datetime]:
    """レシートの日時を datetime に変換"""
    purchase_date = receipt.get("purchase_date") or ""
    purchase_time = str(receipt.get("purchase_time") or "").strip()
    if purchase_date and purchase_time:
        date_part = str(purchase_date).replace("/", "-")
        if " " in date_part:
            date_part = date_part.split(" ")[0]
        dt = _parse_datetime_text(f"{date_part} {purchase_time}")
        if dt:
            return dt
    if purchase_date:
        d = parse_date_only(purchase_date)
        if d:
            return datetime(d.year, d.month, d.day, 23, 59, 59)
    return None


def format_record_time_display(record: Dict[str, Any]) -> str:
    dt = parse_purchase_record_datetime(record)
    if dt:
        return dt.strftime("%Y/%m/%d %H:%M")
    return "時刻不明"


def get_record_sku(record: Dict[str, Any]) -> str:
    sku = str(record.get("SKU") or record.get("sku") or "").strip()
    if not sku or sku in ("未実装", "nan", "None"):
        return ""
    return sku


def get_record_store_code(record: Dict[str, Any]) -> str:
    return normalize_store_code(
        record.get("仕入先") or record.get("店舗コード") or record.get("store_code")
    )


def is_same_day(record: Dict[str, Any], receipt: Dict[str, Any]) -> bool:
    receipt_day = parse_date_only(receipt.get("purchase_date"))
    record_day = parse_date_only(record.get("仕入れ日") or record.get("purchase_date"))
    if receipt_day and record_day:
        return receipt_day == record_day
    receipt_text = str(receipt.get("purchase_date") or "").replace("-", "/")[:10]
    record_text = str(record.get("仕入れ日") or record.get("purchase_date") or "").replace("-", "/")[:10]
    return bool(receipt_text and record_text and receipt_text in record_text)


def is_purchase_before_receipt(record: Dict[str, Any], receipt: Dict[str, Any]) -> bool:
    receipt_dt = parse_receipt_datetime(receipt)
    record_dt = parse_purchase_record_datetime(record)
    if receipt_dt and record_dt:
        return record_dt < receipt_dt
    return True


def sort_receipts_for_bulk_matching(receipts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """レシート時刻が早い順に処理（同一店舗の複数レシートも時刻順）"""

    def sort_key(receipt: Dict[str, Any]) -> Tuple[datetime, str, int]:
        rdt = parse_receipt_datetime(receipt) or datetime.max
        store = normalize_store_code(receipt.get("store_code"))
        rid = int(receipt.get("id") or 0)
        return (rdt, store, rid)

    return sorted(receipts, key=sort_key)


def _skus_by_receipt_image(
    image_file_name: str,
    purchase_records: List[Dict[str, Any]],
    used_skus: Set[str],
) -> List[str]:
    if not image_file_name:
        return []
    found: List[str] = []
    for record in purchase_records:
        record_receipt_id = record.get("レシートID") or record.get("receipt_id", "")
        if str(record_receipt_id) != image_file_name:
            continue
        sku = get_record_sku(record)
        if sku and sku not in used_skus and sku not in found:
            found.append(sku)
    return found


def collect_link_skus_for_receipt(
    receipt: Dict[str, Any],
    purchase_records: List[Dict[str, Any]],
    used_skus: Set[str],
    *,
    store_code: Optional[str] = None,
    image_file_name: Optional[str] = None,
) -> List[str]:
    """
    一括マッチング用: レシート時刻より前の仕入SKUを返す（使用済みSKUは除外）。
    画像ファイル名一致がある場合はそれを優先。
    """
    store = normalize_store_code(store_code or receipt.get("store_code"))
    image_name = image_file_name or ""
    if not image_name:
        file_path = receipt.get("file_path") or receipt.get("original_file_path") or ""
        if file_path:
            image_name = Path(str(file_path)).stem

    by_image = _skus_by_receipt_image(image_name, purchase_records, used_skus)
    if by_image:
        return by_image

    candidates: List[Tuple[datetime, str]] = []
    fallback: List[str] = []

    for record in purchase_records:
        sku = get_record_sku(record)
        if not sku or sku in used_skus:
            continue
        if store and get_record_store_code(record) != store:
            continue
        if not is_same_day(record, receipt):
            continue
        if not is_purchase_before_receipt(record, receipt):
            continue
        record_dt = parse_purchase_record_datetime(record)
        if record_dt:
            candidates.append((record_dt, sku))
        else:
            fallback.append(sku)

    candidates.sort(key=lambda x: x[0])
    ordered = [sku for _, sku in candidates]
    for sku in fallback:
        if sku not in ordered:
            ordered.append(sku)
    return ordered


def build_manual_candidate_entries(
    receipt: Dict[str, Any],
    purchase_records: List[Dict[str, Any]],
    existing_skus: Set[str],
    *,
    purchase_date_str: Optional[str] = None,
    store_code: Optional[str] = None,
    image_file_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    手動調整ダイアログ用候補SKU。
    表示順: 0=画像ファイル名一致, 1=店舗コード一致（同日）, 2=同日（他店舗）
    """
    receipt_for_match = dict(receipt)
    if purchase_date_str:
        receipt_for_match["purchase_date"] = purchase_date_str
    if store_code is not None:
        receipt_for_match["store_code"] = store_code

    store = normalize_store_code(store_code or receipt.get("store_code"))
    image_name = image_file_name or ""
    if not image_name:
        file_path = receipt.get("file_path") or ""
        if file_path:
            image_name = Path(str(file_path)).stem

    entries: List[Dict[str, Any]] = []
    seen: Set[str] = set(existing_skus)

    def append_entry(record: Dict[str, Any], tier: int) -> None:
        sku = get_record_sku(record)
        if not sku or sku in seen:
            return
        seen.add(sku)
        price = record.get("仕入れ価格") or record.get("仕入価格") or record.get("purchase_price") or record.get("cost", 0)
        quantity = record.get("仕入れ個数") or record.get("仕入個数") or record.get("quantity") or record.get("数量", 1)
        try:
            price_f = float(price) if price else 0
            qty_f = float(quantity) if quantity else 1
        except (ValueError, TypeError):
            price_f, qty_f = 0, 1
        product_name = record.get("商品名") or record.get("product_name") or record.get("title") or ""
        time_str = format_record_time_display(record)
        total_amount = int(price_f * qty_f)
        if product_name:
            display_text = f"{sku} - {product_name} - ¥{total_amount:,} - ({time_str})"
        else:
            display_text = f"{sku} - ¥{total_amount:,} - ({time_str})"
        record_dt = parse_purchase_record_datetime(record)
        entries.append(
            {
                "sku": sku,
                "display_text": display_text,
                "tier": tier,
                "sort_dt": record_dt or datetime.min,
            }
        )

    if image_name:
        for record in purchase_records:
            record_receipt_id = record.get("レシートID") or record.get("receipt_id", "")
            if str(record_receipt_id) == image_name:
                append_entry(record, 0)

    tier1: List[Tuple[datetime, Dict[str, Any]]] = []
    tier2: List[Tuple[datetime, Dict[str, Any]]] = []
    for record in purchase_records:
        sku = get_record_sku(record)
        if not sku or sku in seen:
            continue
        if not is_same_day(record, receipt_for_match):
            continue
        if not is_purchase_before_receipt(record, receipt_for_match):
            continue
        record_dt = parse_purchase_record_datetime(record) or datetime.min
        if store and get_record_store_code(record) == store:
            tier1.append((record_dt, record))
        else:
            tier2.append((record_dt, record))

    tier1.sort(key=lambda x: x[0])
    tier2.sort(key=lambda x: x[0])
    for _, record in tier1:
        append_entry(record, 1)
    for _, record in tier2:
        append_entry(record, 2)

    entries.sort(key=lambda e: (e["tier"], e["sort_dt"]))
    return entries
