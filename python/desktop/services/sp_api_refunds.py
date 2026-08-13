#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API から返品・返金情報を取得し、販売DB更新用の辞書にする。

方針:
- Finances API（返金額の正）は Finance ロールが必要なため、使えるときだけ使う
- 使えるロール向けに Reports API を主経路にする
  - FBA: GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA（料金ロールで可）
  - 自己発送含む: GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE（在庫と注文の追跡で可・Refunded Amount あり）
"""

from __future__ import annotations

import csv
import gzip
import io
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import requests

try:
    from services.sp_api_orders import build_sp_api_client, created_after_iso
except ImportError:
    from desktop.services.sp_api_orders import build_sp_api_client, created_after_iso  # type: ignore


REPORT_FBA_RETURNS = "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA"
REPORT_FLAT_RETURNS = "GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE"


def _payload(body: Dict[str, Any]) -> Dict[str, Any]:
    payload = body.get("payload")
    if isinstance(payload, dict):
        return payload
    return body if isinstance(body, dict) else {}


def _to_int_money(value: Any) -> int:
    if value is None:
        return 0
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "none", "-"):
        return 0
    try:
        return int(round(abs(float(text))))
    except (TypeError, ValueError):
        return 0


def _to_int_qty(value: Any, default: int = 1) -> int:
    n = _to_int_money(value)
    return n if n > 0 else default


def parse_tsv_text(text: str) -> List[Dict[str, str]]:
    """タブ区切りレポートを dict 行のリストにする。"""
    raw = (text or "").lstrip("\ufeff")
    if not raw.strip():
        return []
    reader = csv.DictReader(io.StringIO(raw), delimiter="\t")
    rows: List[Dict[str, str]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        cleaned = {str(k).strip(): ("" if v is None else str(v).strip()) for k, v in row.items() if k}
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def download_report_document(doc_body: Dict[str, Any]) -> str:
    """report document の URL から本文テキストを取得する。"""
    payload = _payload(doc_body)
    url = str(payload.get("url") or "").strip()
    if not url:
        raise RuntimeError("report document に url がありません。")
    response = requests.get(url, timeout=120)
    if response.status_code >= 400:
        raise RuntimeError(f"レポートダウンロード失敗: HTTP {response.status_code}")
    data = response.content
    if str(payload.get("compressionAlgorithm") or "").upper() == "GZIP":
        data = gzip.decompress(data)
    # JP レポートは UTF-8 か Shift_JIS のことがある
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def wait_report_done(
    client: Any,
    report_id: str,
    *,
    poll_sec: float = 3.0,
    timeout_sec: float = 300.0,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """レポートが DONE になるまで待つ。"""
    started = time.time()
    while True:
        if should_cancel and should_cancel():
            raise RuntimeError("キャンセルされました")
        body = client.get_report(report_id)
        payload = _payload(body)
        status = str(payload.get("processingStatus") or "").upper()
        if on_progress:
            on_progress(f"レポート処理中… {status} ({report_id})")
        if status == "DONE":
            return payload
        if status in ("FATAL", "CANCELLED", "CANCELED"):
            raise RuntimeError(f"レポート失敗: status={status} detail={payload}")
        if time.time() - started > timeout_sec:
            raise RuntimeError(f"レポートタイムアウト: status={status}")
        time.sleep(max(1.0, float(poll_sec)))


def fetch_report_rows(
    client: Any,
    report_type: str,
    *,
    days: int = 30,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """
    レポート1種を作成→完了待ち→TSV行取得。

    Returns:
        (rows, error_message_or_None)
    """
    try:
        start = created_after_iso(days=days)
        if on_progress:
            on_progress(f"レポート作成: {report_type}")
        created = client.create_report(report_type, data_start_time=start)
        report_id = str(_payload(created).get("reportId") or created.get("reportId") or "").strip()
        if not report_id:
            return [], f"{report_type}: reportId がありません"
        done = wait_report_done(
            client,
            report_id,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
        doc_id = str(done.get("reportDocumentId") or "").strip()
        if not doc_id:
            return [], f"{report_type}: reportDocumentId がありません"
        if on_progress:
            on_progress(f"レポートダウンロード: {report_type}")
        doc = client.get_report_document(doc_id)
        text = download_report_document(doc)
        return parse_tsv_text(text), None
    except Exception as exc:  # noqa: BLE001
        return [], f"{report_type}: {exc}"


def fba_return_row_to_refund(row: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """FBA返品レポート1行 → 返金更新用 dict。"""
    order_id = str(row.get("order-id") or row.get("Order ID") or "").strip()
    sku = str(row.get("sku") or row.get("Merchant SKU") or "").strip()
    if not order_id or not sku:
        return None
    qty = _to_int_qty(row.get("quantity") or row.get("Return quantity"), default=1)
    return {
        "order_id": order_id,
        "sku": sku,
        "return_quantity": qty,
        "refund_amount": None,  # FBAレポートに金額列なし → 販売価格から推定
        "return_date": str(row.get("return-date") or "").strip(),
        "reason": str(row.get("reason") or "").strip(),
        "status": str(row.get("status") or row.get("detailed-disposition") or "").strip(),
        "source": "fba_returns_report",
    }


def flat_return_row_to_refund(row: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """自己発送向け返品レポート1行 → 返金更新用 dict。"""
    order_id = str(row.get("Order ID") or row.get("order-id") or "").strip()
    sku = str(row.get("Merchant SKU") or row.get("sku") or "").strip()
    if not order_id or not sku:
        return None
    status = str(row.get("Return request status") or "").strip()
    # キャンセルされた返品依頼は除外
    if status.lower() in ("cancelled", "canceled", "拒否", "取消"):
        return None
    qty = _to_int_qty(row.get("Return quantity") or row.get("quantity"), default=1)
    amount = _to_int_money(row.get("Refunded Amount"))
    return {
        "order_id": order_id,
        "sku": sku,
        "return_quantity": qty,
        "refund_amount": amount if amount > 0 else None,
        "return_date": str(row.get("Return request date") or row.get("Return delivery date") or "").strip(),
        "reason": str(row.get("Return Reason") or "").strip(),
        "status": status,
        "source": "flat_returns_report",
    }


def parse_finance_refund_events(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Finances FinancialEvents.RefundEventList を正規化する。"""
    payload = _payload(body)
    events = payload.get("FinancialEvents") or {}
    if not isinstance(events, dict):
        return []
    refunds = events.get("RefundEventList") or []
    out: List[Dict[str, Any]] = []
    if not isinstance(refunds, list):
        return out
    for event in refunds:
        if not isinstance(event, dict):
            continue
        order_id = str(event.get("AmazonOrderId") or "").strip()
        items = event.get("ShipmentItemAdjustmentList") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("SellerSKU") or "").strip()
            if not order_id or not sku:
                continue
            amount = 0
            for charge in item.get("ItemChargeAdjustmentList") or []:
                if not isinstance(charge, dict):
                    continue
                # Principal など返金本体
                node = charge.get("ChargeAmount") or {}
                amount += _to_int_money(node.get("CurrencyAmount") if isinstance(node, dict) else node)
            qty = _to_int_qty(item.get("QuantityShipped"), default=1)
            out.append(
                {
                    "order_id": order_id,
                    "sku": sku,
                    "return_quantity": qty,
                    "refund_amount": amount if amount > 0 else None,
                    "return_date": str(event.get("PostedDate") or "").strip(),
                    "reason": "RefundEvent",
                    "status": "Refunded",
                    "source": "finances_api",
                }
            )
    return out


def merge_refund_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一 order_id+sku を合算する（数量・金額）。"""
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in records:
        key = (str(rec.get("order_id") or ""), str(rec.get("sku") or ""))
        if not key[0] or not key[1]:
            continue
        cur = merged.get(key)
        if cur is None:
            merged[key] = dict(rec)
            continue
        cur["return_quantity"] = int(cur.get("return_quantity") or 0) + int(rec.get("return_quantity") or 0)
        a = rec.get("refund_amount")
        if a is not None:
            cur["refund_amount"] = int(cur.get("refund_amount") or 0) + int(a)
        # より情報のある source を残す
        if cur.get("refund_amount") and rec.get("source") == "finances_api":
            cur["source"] = "finances_api"
        elif not cur.get("refund_amount") and rec.get("refund_amount"):
            cur["source"] = rec.get("source")
        if rec.get("reason") and not cur.get("reason"):
            cur["reason"] = rec.get("reason")
    return list(merged.values())


def estimate_refund_amount(sale: Mapping[str, Any], refund: Mapping[str, Any]) -> int:
    """返金額が無いとき、販売価格×返品数/販売数で推定する。"""
    explicit = refund.get("refund_amount")
    if explicit is not None and int(explicit) > 0:
        return int(explicit)
    sale_price = _to_int_money(sale.get("sale_price"))
    sale_qty = max(1, _to_int_qty(sale.get("quantity"), default=1))
    ret_qty = max(1, _to_int_qty(refund.get("return_quantity"), default=1))
    ret_qty = min(ret_qty, sale_qty)
    return int(round(sale_price * ret_qty / sale_qty))


def apply_refund_to_sale(sale: Dict[str, Any], refund: Mapping[str, Any]) -> Dict[str, Any]:
    """
    販売レコードに返金総額を反映し、利益を再計算する。

    利益 = 販売価格 - 手数料類 - 返金総額
    （仕入原価込みの利益は呼び出し側で既に net_profit に入っている場合があるため、
     既存利益から増分返金を差し引く方式も併用）
    """
    new_refund = estimate_refund_amount(sale, refund)
    old_refund = _to_int_money(sale.get("refund_total"))
    # 大きい方を採用（再取込で減らないように）
    refund_total = max(old_refund, new_refund)
    sale["refund_total"] = refund_total

    sale_price = _to_int_money(sale.get("sale_price"))
    fees = (
        _to_int_money(sale.get("platform_fee"))
        + _to_int_money(sale.get("shipping_fee"))
        + _to_int_money(sale.get("fba_fee"))
        + _to_int_money(sale.get("storage_fee"))
        + _to_int_money(sale.get("other_fees"))
    )
    if sale_price > 0:
        # 既存利益に仕入原価が含まれる場合: (sale - fees - cost) - refund
        # cost が不明でも、旧利益があれば増分だけ差し引く
        old_profit = sale.get("net_profit")
        if old_profit is not None and old_refund >= 0:
            try:
                base_without_refund = int(old_profit) + old_refund
                sale["net_profit"] = base_without_refund - refund_total
            except (TypeError, ValueError):
                sale["net_profit"] = sale_price - fees - refund_total
        else:
            sale["net_profit"] = sale_price - fees - refund_total
    return sale


def fetch_refund_records_from_sp_api(
    client: Any,
    *,
    days: int = 30,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    返品・返金レコードを集約して返す。

    Returns:
        dict: refunds, errors, finances_available, canceled, reports_used
    """
    errors: List[str] = []
    records: List[Dict[str, Any]] = []
    finances_available = False
    canceled = False
    reports_used: List[str] = []

    # 1) Finances（ロールがあれば金額の正）
    try:
        if on_progress:
            on_progress("Finances API で返金イベントを確認中…")
        posted_after = created_after_iso(days=days)
        body = client.list_financial_events(posted_after=posted_after)
        fin_rows = parse_finance_refund_events(body)
        records.extend(fin_rows)
        finances_available = True
        if on_progress:
            on_progress(f"Finances 返金イベント: {len(fin_rows)} 件")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "403" in msg or "Unauthorized" in msg:
            errors.append(
                "Finances API は未許可（返金額の実額取得には「財務と会計」ロールが必要）。"
                "返品レポートから推定・反映します。"
            )
        else:
            errors.append(f"Finances: {exc}")

    if should_cancel and should_cancel():
        return {
            "refunds": merge_refund_records(records),
            "errors": errors,
            "finances_available": finances_available,
            "canceled": True,
            "reports_used": reports_used,
        }

    # 2) FBA 返品レポート
    fba_rows, fba_err = fetch_report_rows(
        client,
        REPORT_FBA_RETURNS,
        days=days,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    if fba_err:
        if "キャンセル" in fba_err:
            canceled = True
        errors.append(fba_err)
    else:
        reports_used.append(REPORT_FBA_RETURNS)
        for row in fba_rows:
            rec = fba_return_row_to_refund(row)
            if rec:
                records.append(rec)

    if should_cancel and should_cancel():
        canceled = True
    else:
        # 3) フラット返品レポート（Refunded Amount あり）
        flat_rows, flat_err = fetch_report_rows(
            client,
            REPORT_FLAT_RETURNS,
            days=days,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
        if flat_err:
            if "キャンセル" in flat_err:
                canceled = True
            errors.append(flat_err)
        else:
            reports_used.append(REPORT_FLAT_RETURNS)
            for row in flat_rows:
                rec = flat_return_row_to_refund(row)
                if rec:
                    records.append(rec)

    return {
        "refunds": merge_refund_records(records),
        "errors": errors,
        "finances_available": finances_available,
        "canceled": canceled,
        "reports_used": reports_used,
    }
