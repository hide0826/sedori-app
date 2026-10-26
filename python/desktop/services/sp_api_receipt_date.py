#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FBA倉庫の受領日から、残在庫の一番古い受領日を決める。

出品日はこの日付に揃える。自己発送・在庫0・受領履歴が足りないSKUは更新しない。
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# 旧 GET_FBA_FULFILLMENT_INVENTORY_RECEIPTS_DATA は
# 「report type 2607 is not allowed」で拒否される。台帳の受領イベントを使う。
REPORT_FBA_RECEIPTS = "GET_LEDGER_DETAIL_VIEW_DATA"
REPORT_FBA_WAREHOUSE = "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA"
RECEIPT_INITIAL_LOOKBACK_DAYS = 540
RECEIPT_OVERLAP_DAYS = 3
RECEIPT_REPORT_TIMEOUT_SEC = 1800.0
RECEIPT_CREATE_INTERVAL_SEC = 75.0
RECEIPT_QUOTA_RETRY_WAIT_SEC = 120.0
RECEIPT_QUOTA_RETRIES = 5

_DATE_KEYS = (
    "received-date",
    "received date",
    "receipt-date",
    "date and time",
    "date",
    "受領日",
    "日付",
    "日時",
)
_SKU_KEYS = (
    "sku",
    "seller-sku",
    "merchant-sku",
    "msku",
    "出品者sku",
    "出品者SKU",
)
_QTY_KEYS = ("quantity", "qty", "数量", "受領数")
_SHIPMENT_KEYS = ("fba-shipment-id", "shipment-id", "reference id", "納品番号", "参照id")
_FC_KEYS = (
    "fulfillment-center-id",
    "fulfillment-center",
    "fulfillment center",
    "フルフィルメントセンター",
    "フルフィルメント・センター",
)

_CHANNEL_KEYS = (
    "fulfillment-channel",
    "fulfilment-channel",
    "フルフィルメント・チャンネル",
    "フルフィルメントチャンネル",
)
_ON_HAND_QTY_KEYS = (
    "在庫数",
    "afn-warehouse-quantity",
    "afn-fulfillable-quantity",
    "quantity",
    "数量",
)
# 出品レポートの「在庫数」「数量」は FBA だと空欄。倉庫数は MYI のこちらを使う。
_WAREHOUSE_QTY_KEYS = (
    "afn-warehouse-quantity",
    "afn-fulfillable-quantity",
    "quantity available",
    "quantity-available",
)


def _normalize_header(name: Any) -> str:
    text = str(name or "").replace("\ufeff", "").strip().lower()
    text = text.replace("　", "").replace(" ", "").replace("_", "-")
    text = re.sub(r"-+", "-", text)
    return text


def _row_value(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    norm = {_normalize_header(k): v for k, v in row.items() if k is not None}
    for key in keys:
        raw = norm.get(_normalize_header(key))
        if raw is None:
            continue
        text = str(raw).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return ""


def parse_receipt_day(raw: Any) -> Optional[date]:
    """受領日文字列を date にする。読めなければ None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    text = text.replace(".", "-").replace("/", "-")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        compact = "".join(ch for ch in text if ch.isdigit())[:8]
        try:
            return datetime.strptime(compact, "%Y%m%d").date()
        except ValueError:
            return None


def format_listed_date(day: date) -> str:
    """仕入DBの出品日表示（YYYY/MM/DD）。"""
    return day.strftime("%Y/%m/%d")


def _to_qty(raw: Any) -> int:
    text = str(raw or "").strip().replace(",", "")
    if not text:
        return 0
    try:
        qty = int(round(float(text)))
    except (TypeError, ValueError):
        return 0
    return qty if qty > 0 else 0


def is_fba_channel(channel: str) -> bool:
    """フルフィルメントが FBA（AMAZON）か。空や自己発送は False。"""
    text = str(channel or "").strip().upper()
    if not text:
        return False
    return "AMAZON" in text


def receipt_events_from_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """受領レポート行を sku / date / qty に揃える。"""
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sku = _row_value(row, _SKU_KEYS)
        day = parse_receipt_day(_row_value(row, _DATE_KEYS))
        qty = _to_qty(_row_value(row, _QTY_KEYS))
        if not sku or day is None or qty <= 0:
            continue
        out.append(
            {
                "sku": sku,
                "date": day.isoformat(),
                "qty": qty,
                "shipment_id": _row_value(row, _SHIPMENT_KEYS),
                "fc": _row_value(row, _FC_KEYS),
            }
        )
    return out


def merge_receipt_events(events: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """同じSKU・日・納品・倉庫は個数を足して1行にする。"""
    merged: Dict[Tuple[str, str, str, str], int] = {}
    for event in events:
        sku = str(event.get("sku") or "").strip()
        day = str(event.get("date") or "").strip()
        if not sku or not day:
            continue
        qty = _to_qty(event.get("qty"))
        if qty <= 0:
            continue
        key = (
            sku,
            day,
            str(event.get("shipment_id") or "").strip(),
            str(event.get("fc") or "").strip(),
        )
        merged[key] = merged.get(key, 0) + qty
    rows = [
        {
            "sku": sku,
            "date": day,
            "qty": qty,
            "shipment_id": shipment_id,
            "fc": fc,
        }
        for (sku, day, shipment_id, fc), qty in merged.items()
    ]
    rows.sort(key=lambda item: (item["sku"], item["date"], item["shipment_id"], item["fc"]))
    return rows


def oldest_remaining_receipt_date(
    events: Iterable[Mapping[str, Any]],
    on_hand_qty: int,
) -> Optional[date]:
    """
    残っている在庫の一番古い受領日。

    在庫0、受領なし、受領合計が現在庫より少ないときは None（上書きしない）。
    """
    try:
        on_hand = int(on_hand_qty)
    except (TypeError, ValueError):
        return None
    if on_hand <= 0:
        return None
    by_day: Dict[date, int] = {}
    for event in events:
        day = parse_receipt_day(event.get("date"))
        qty = _to_qty(event.get("qty"))
        if day is None or qty <= 0:
            continue
        by_day[day] = by_day.get(day, 0) + qty
    if not by_day:
        return None
    total = sum(by_day.values())
    if total < on_hand:
        return None
    consume = total - on_hand
    for day in sorted(by_day):
        qty = by_day[day]
        if consume >= qty:
            consume -= qty
            continue
        return day
    return None


def fba_on_hand_by_sku(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """出品レポートから FBA の在庫数を SKU ごとに足す。自己発送は含めない。"""
    totals: Dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not is_fba_channel(_row_value(row, _CHANNEL_KEYS)):
            continue
        sku = _row_value(row, _SKU_KEYS)
        qty = _to_qty(_row_value(row, _ON_HAND_QTY_KEYS))
        if not sku or qty <= 0:
            continue
        totals[sku] = totals.get(sku, 0) + qty
    return totals


def fba_warehouse_on_hand_by_sku(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """FBA在庫レポートの倉庫在庫。0以下とSKUなしは含めない。"""
    totals: Dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sku = _row_value(row, _SKU_KEYS)
        qty = _to_qty(_row_value(row, _WAREHOUSE_QTY_KEYS))
        if not sku or qty <= 0:
            continue
        totals[sku] = totals.get(sku, 0) + qty
    return totals


def listed_dates_for_fba_stock(
    on_hand_by_sku: Mapping[str, int],
    events: Iterable[Mapping[str, Any]],
) -> Dict[str, str]:
    """更新してよい SKU → 出品日（YYYY/MM/DD）。取れないSKUは含めない。"""
    by_sku: Dict[str, List[Mapping[str, Any]]] = {}
    for event in events:
        sku = str(event.get("sku") or "").strip()
        if sku:
            by_sku.setdefault(sku, []).append(event)
    out: Dict[str, str] = {}
    for sku, qty in on_hand_by_sku.items():
        day = oldest_remaining_receipt_date(by_sku.get(sku, []), int(qty))
        if day is None:
            continue
        out[sku] = format_listed_date(day)
    return out


def receipt_cache_path() -> Path:
    path = Path(__file__).resolve().parents[1] / "logs" / "fba_receipts_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_receipt_cache(path: Optional[Path] = None) -> Dict[str, Any]:
    cache_path = path or receipt_cache_path()
    if not cache_path.exists():
        return {"covered_through": "", "events": []}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"covered_through": "", "events": []}
    if not isinstance(data, dict):
        return {"covered_through": "", "events": []}
    events = data.get("events")
    if not isinstance(events, list):
        events = []
    return {
        "covered_through": str(data.get("covered_through") or ""),
        "events": [row for row in events if isinstance(row, dict)],
    }


def save_receipt_cache(cache: Mapping[str, Any], path: Optional[Path] = None) -> None:
    cache_path = path or receipt_cache_path()
    payload = {
        "covered_through": str(cache.get("covered_through") or ""),
        "events": merge_receipt_events(list(cache.get("events") or [])),
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def month_windows(start: date, end: date) -> List[Tuple[date, date]]:
    """受領レポートを月ごとに分ける。"""
    if end < start:
        return []
    windows: List[Tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        window_end = min(end, next_month - timedelta(days=1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _iso_start(day: date) -> str:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_end(day: date) -> str:
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _payload(body: Dict[str, Any]) -> Dict[str, Any]:
    payload = body.get("payload")
    if isinstance(payload, dict):
        return payload
    return body if isinstance(body, dict) else {}


def events_replacing_range(
    existing: Iterable[Mapping[str, Any]],
    fresh: Iterable[Mapping[str, Any]],
    start: date,
    end: date,
) -> List[Dict[str, Any]]:
    """期間内の古い受領を捨て、同じ期間の新しい行で入れ替える。"""
    kept: List[Mapping[str, Any]] = []
    for event in existing:
        day = parse_receipt_day(event.get("date"))
        if day is None or day < start or day > end:
            kept.append(event)
    return merge_receipt_events([*kept, *fresh])


def _report_columns(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    return ", ".join(str(key) for key in list(rows[0].keys())[:12])


def _latest_done_report(client: Any, report_type: str, max_age_sec: float) -> Optional[Dict[str, Any]]:
    """直近に完成した同じ種類のレポートがあれば、新規作成せず再利用する。"""
    if not hasattr(client, "list_reports"):
        return None
    since = (datetime.now(timezone.utc) - timedelta(seconds=max_age_sec)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        body = client.list_reports(
            report_types=[report_type],
            processing_statuses=["DONE"],
            created_since=since,
            page_size=10,
        )
    except Exception:
        return None
    reports = body.get("reports") if isinstance(body, dict) else None
    if not isinstance(reports, list) and isinstance(body, dict):
        payload = body.get("payload")
        if isinstance(payload, dict):
            reports = payload.get("reports")
    if not isinstance(reports, list):
        return None
    best: Optional[Dict[str, Any]] = None
    best_time = ""
    for row in reports:
        if not isinstance(row, dict):
            continue
        if not str(row.get("reportDocumentId") or "").strip():
            continue
        created = str(row.get("createdTime") or "")
        if best is None or created > best_time:
            best = row
            best_time = created
    return best


def fetch_fba_warehouse_on_hand(
    client: Any,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, int]:
    """いま倉庫にある FBA 在庫数。出品レポートの在庫数は FBA だと空なので使わない。"""
    try:
        from services.sp_api_refunds import download_report_document, parse_tsv_text, wait_report_done
    except ImportError:
        from desktop.services.sp_api_refunds import (  # type: ignore
            download_report_document,
            parse_tsv_text,
            wait_report_done,
        )

    done = _latest_done_report(client, REPORT_FBA_WAREHOUSE, max_age_sec=90 * 60)
    if done is not None:
        if on_progress:
            on_progress(
                f"直近のFBA在庫レポートを再利用: {done.get('reportId')} "
                f"({done.get('createdTime') or ''})"
            )
    else:
        if on_progress:
            on_progress(f"FBA在庫レポートを取得中… {REPORT_FBA_WAREHOUSE}")
        created = client.create_report(REPORT_FBA_WAREHOUSE)
        report_id = str(_payload(created).get("reportId") or created.get("reportId") or "").strip()
        if not report_id:
            raise RuntimeError(f"{REPORT_FBA_WAREHOUSE}: reportId がありません")
        done = wait_report_done(
            client,
            report_id,
            timeout_sec=RECEIPT_REPORT_TIMEOUT_SEC,
            on_progress=on_progress,
        )
    doc_id = str(done.get("reportDocumentId") or "").strip()
    if not doc_id:
        raise RuntimeError(f"{REPORT_FBA_WAREHOUSE}: reportDocumentId がありません")
    rows = parse_tsv_text(download_report_document(client.get_report_document(doc_id)))
    on_hand = fba_warehouse_on_hand_by_sku(rows)
    if on_progress:
        on_progress(
            f"FBA在庫レポート {len(rows)} 行 / 在庫あり {len(on_hand)} SKU"
            f"（列: {_report_columns(rows)}）"
        )
    return on_hand


def _create_receipt_report(
    client: Any,
    window_start: date,
    window_end: date,
    *,
    last_create: float,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """受領レポートを作る。作成間隔を空け、回数制限のときは待ってやり直す。"""
    if last_create:
        remain = RECEIPT_CREATE_INTERVAL_SEC - (time.monotonic() - last_create)
        if remain > 0:
            time.sleep(remain)
    last_exc: Optional[BaseException] = None
    for attempt in range(RECEIPT_QUOTA_RETRIES + 1):
        try:
            return client.create_report(
                REPORT_FBA_RECEIPTS,
                data_start_time=_iso_start(window_start),
                data_end_time=_iso_end(window_end),
                report_options={"eventType": "Receipts"},
            )
        except Exception as exc:
            text = str(exc)
            if "403" in text or "Unauthorized" in text:
                raise RuntimeError(
                    "受領の在庫台帳を取る権限がありません（Amazon Fulfillment）。"
                    "出品日は変更していません。"
                ) from exc
            if "429" not in text and "QuotaExceeded" not in text:
                raise
            last_exc = exc
            if attempt >= RECEIPT_QUOTA_RETRIES:
                break
            if on_progress:
                on_progress(
                    "受領レポートの作成が混み合っています。"
                    f"{int(RECEIPT_QUOTA_RETRY_WAIT_SEC)}秒待って再試行します"
                    f"（{attempt + 1}/{RECEIPT_QUOTA_RETRIES}）"
                )
            time.sleep(RECEIPT_QUOTA_RETRY_WAIT_SEC)
    raise last_exc if last_exc is not None else RuntimeError("受領レポートを作成できません")


def fetch_receipt_events(
    client: Any,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
    lookback_days: int = RECEIPT_INITIAL_LOOKBACK_DAYS,
    cache_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    受領レポートを期間分割で取り、キャッシュへ足して全イベントを返す。

    途中で失敗した月は covered_through を進めない。
    """
    try:
        from services.sp_api_refunds import download_report_document, parse_tsv_text, wait_report_done
    except ImportError:
        from desktop.services.sp_api_refunds import (  # type: ignore
            download_report_document,
            parse_tsv_text,
            wait_report_done,
        )

    today = datetime.now(timezone.utc).date()
    cache = load_receipt_cache(cache_path)
    covered = parse_receipt_day(cache.get("covered_through"))
    if covered is None:
        start = today - timedelta(days=max(1, int(lookback_days)))
    else:
        start = covered - timedelta(days=RECEIPT_OVERLAP_DAYS)
    if start > today:
        start = today

    events = list(cache.get("events") or [])
    if hasattr(client, "_quota_max_retries"):
        client._quota_max_retries = 0
        client._quota_base_wait_sec = 45.0
    last_create = 0.0
    for window_start, window_end in month_windows(start, today):
        if on_progress:
            on_progress(f"受領レポート {window_start.isoformat()} 〜 {window_end.isoformat()}")
        created = _create_receipt_report(
            client,
            window_start,
            window_end,
            last_create=last_create,
            on_progress=on_progress,
        )
        last_create = time.monotonic()
        report_id = str(_payload(created).get("reportId") or created.get("reportId") or "").strip()
        if not report_id:
            raise RuntimeError(f"{REPORT_FBA_RECEIPTS}: reportId がありません")
        done = wait_report_done(
            client,
            report_id,
            timeout_sec=RECEIPT_REPORT_TIMEOUT_SEC,
            on_progress=on_progress,
        )
        doc_id = str(done.get("reportDocumentId") or "").strip()
        if not doc_id:
            raise RuntimeError(f"{REPORT_FBA_RECEIPTS}: reportDocumentId がありません")
        doc = client.get_report_document(doc_id)
        rows = parse_tsv_text(download_report_document(doc))
        if on_progress and not events:
            on_progress(f"受領レポート列: {_report_columns(rows)}")
        events = events_replacing_range(
            events,
            receipt_events_from_rows(rows),
            window_start,
            window_end,
        )
        cache = {"covered_through": window_end.isoformat(), "events": events}
        save_receipt_cache(cache, cache_path)
        if on_progress:
            on_progress(f"受領キャッシュ {len(events)} 件（〜{window_end.isoformat()}）")
    return merge_receipt_events(events)


def apply_receipt_listed_dates(
    purchase_db: Any,
    listed_by_sku: Mapping[str, str],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    """
    仕入DBにあるSKUだけ出品日を上書きする。

    ステータスが空または出品可能（ready）のときだけ販売中にする。
    """
    moment = now or datetime.now()
    summary = {
        "updated": 0,
        "status_selling": 0,
        "unchanged": 0,
        "skipped_missing": 0,
    }
    for sku, listed in listed_by_sku.items():
        sku_text = str(sku or "").strip()
        listed_text = str(listed or "").strip()
        if not sku_text or not listed_text:
            continue
        existing = purchase_db.get_by_sku(sku_text)
        if not existing:
            summary["skipped_missing"] += 1
            continue
        payload: Dict[str, Any] = {"sku": sku_text}
        current = str(existing.get("listed_date") or "").strip()
        if current != listed_text:
            payload["listed_date"] = listed_text
        status = str(existing.get("status") or "").strip().lower()
        if status in ("", "ready"):
            payload["status"] = "selling"
            payload["status_reason"] = "受領日を出品日に設定"
            payload["status_set_at"] = moment.strftime("%Y-%m-%d %H:%M:%S")
            summary["status_selling"] += 1
        if len(payload) == 1:
            summary["unchanged"] += 1
            continue
        purchase_db.upsert(payload)
        summary["updated"] += 1
    return summary
