#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
販売DB・仕入ステータスへの反映（画面ボタンと毎朝のタスクで共用）。

- 注文 → 販売DB、仕入は販売済み / 一部販売済み
- 返品 → 販売DBの返金総額
- そのSKUの販売がすべて返金なら仕入ステータスを返金にする
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional

try:
    from services.sp_api_orders import (
        SALE_COUNTABLE_TX_METHODS,
        enrich_sales_with_purchase_fees,
        fetch_sale_payloads_from_sp_api,
    )
    from services.sp_api_refunds import apply_refund_to_sale, fetch_refund_records_from_sp_api
except ImportError:
    from desktop.services.sp_api_orders import (  # type: ignore
        SALE_COUNTABLE_TX_METHODS,
        enrich_sales_with_purchase_fees,
        fetch_sale_payloads_from_sp_api,
    )
    from desktop.services.sp_api_refunds import (  # type: ignore
        apply_refund_to_sale,
        fetch_refund_records_from_sp_api,
    )


_STATUS_SKIP_SALES = frozenset({"inventory_only"})
_STATUS_SKIP_REFUND = frozenset(
    {"inventory_only", "damaged", "unlistable", "storage", "pending"}
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in ("nan", "none"):
        return ""
    return text


def to_int_amount(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in ("nan", "none"):
        return default
    try:
        return int(round(float(text)))
    except (TypeError, ValueError):
        return default


def to_int_count(value: Any, default: int = 1) -> int:
    count = to_int_amount(value, default=default)
    return count if count > 0 else default


def normalize_sale_date_key(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if "T" in text:
        text = text.split("T", 1)[0]
    normalized = text.replace(".", "-").replace("/", "-")[:10]
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        compact = "".join(ch for ch in text if ch.isdigit())[:8]
        try:
            return datetime.strptime(compact, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return text


def build_sale_dedupe_key(sale: Mapping[str, Any]) -> tuple:
    order_id = normalize_text(sale.get("order_id"))
    sku = normalize_text(sale.get("sku"))
    if order_id and sku:
        return ("order_sku", order_id, sku)
    return (
        "fallback",
        sku,
        normalize_sale_date_key(sale.get("sale_date")),
        to_int_amount(sale.get("sale_price"), default=0),
    )


def _countable_tx(sale: Mapping[str, Any]) -> bool:
    tx = normalize_text(sale.get("transaction_method")).lower().replace(" ", "")
    return tx in SALE_COUNTABLE_TX_METHODS


def upsert_sales_payloads(sales_db: Any, payloads: List[Dict[str, Any]]) -> Dict[str, int]:
    """販売レコードを重複キーで insert / update する。"""
    existing_sales = sales_db.list_all()
    existing_by_key: Dict[tuple, Dict[str, Any]] = {}
    provisional_by_sku_date: Dict[tuple, Dict[str, Any]] = {}
    for sale in existing_sales:
        key = build_sale_dedupe_key(sale)
        if key not in existing_by_key:
            existing_by_key[key] = sale
        price = to_int_amount(sale.get("sale_price"), default=0)
        sku = normalize_text(sale.get("sku"))
        sale_date = normalize_sale_date_key(sale.get("sale_date"))
        if price <= 0 and sku and sale_date:
            sd_key = (sku, sale_date)
            if sd_key not in provisional_by_sku_date:
                provisional_by_sku_date[sd_key] = sale

    inserted = 0
    updated = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    imported_keys = set()

    for sale_payload in payloads:
        sku = normalize_text(sale_payload.get("sku"))
        sale_date_full = normalize_text(sale_payload.get("sale_date"))
        sale_date = normalize_sale_date_key(sale_date_full)
        if not sku or not sale_date:
            skipped_invalid += 1
            continue
        sale_payload = {**sale_payload, "sale_date": sale_date_full or sale_date}
        dedupe_key = build_sale_dedupe_key(sale_payload)
        existing_sale = existing_by_key.get(dedupe_key)
        if existing_sale is None:
            provisional = provisional_by_sku_date.get((sku, sale_date))
            if provisional is not None:
                existing_sale = provisional

        if existing_sale is not None:
            existing_price = to_int_amount(existing_sale.get("sale_price"), default=0)
            incoming_price = to_int_amount(sale_payload.get("sale_price"), default=0)
            existing_tx = normalize_text(existing_sale.get("transaction_method"))
            incoming_tx = normalize_text(sale_payload.get("transaction_method"))
            should_update = False
            existing_fee_sum = (
                to_int_amount(existing_sale.get("platform_fee"), 0)
                + to_int_amount(existing_sale.get("shipping_fee"), 0)
                + to_int_amount(existing_sale.get("fba_fee"), 0)
                + to_int_amount(existing_sale.get("other_fees"), 0)
            )
            incoming_fee_sum = (
                to_int_amount(sale_payload.get("platform_fee"), 0)
                + to_int_amount(sale_payload.get("shipping_fee"), 0)
                + to_int_amount(sale_payload.get("fba_fee"), 0)
                + to_int_amount(sale_payload.get("other_fees"), 0)
            )
            if existing_price <= 0 and incoming_price > 0:
                should_update = True
            elif existing_price <= 0 and incoming_price <= 0:
                if normalize_text(sale_payload.get("order_id")) and not normalize_text(
                    existing_sale.get("order_id")
                ):
                    should_update = True
                elif incoming_tx and incoming_tx != existing_tx:
                    should_update = True
            elif incoming_tx and incoming_tx != existing_tx:
                should_update = True
            elif existing_fee_sum <= 0 and incoming_fee_sum > 0:
                should_update = True
            elif existing_sale.get("net_profit") is None and sale_payload.get("net_profit") is not None:
                should_update = True

            if should_update:
                target_id = existing_sale.get("id")
                if target_id:
                    merged = dict(sale_payload)
                    fee_keys = (
                        "platform_fee",
                        "shipping_fee",
                        "fba_fee",
                        "storage_fee",
                        "other_fees",
                        "refund_total",
                        "net_profit",
                    )
                    incoming_fees_zero = all(
                        to_int_amount(sale_payload.get(key), default=0) == 0
                        for key in fee_keys
                        if key != "net_profit"
                    )
                    if incoming_fees_zero:
                        for key in fee_keys:
                            if key in existing_sale and existing_sale.get(key) is not None:
                                if key == "net_profit" or to_int_amount(
                                    existing_sale.get(key), default=0
                                ) != 0:
                                    merged[key] = existing_sale.get(key)
                    if incoming_price <= 0 < existing_price:
                        merged["sale_price"] = existing_price
                    sales_db.update(int(target_id), merged)
                    updated += 1
                    updated_row = {**existing_sale, **merged}
                    existing_by_key[dedupe_key] = updated_row
                    existing_by_key[build_sale_dedupe_key(updated_row)] = updated_row
                    if to_int_amount(updated_row.get("sale_price"), default=0) <= 0:
                        provisional_by_sku_date[(sku, sale_date)] = updated_row
                    else:
                        provisional_by_sku_date.pop((sku, sale_date), None)
                    continue
            skipped_duplicate += 1
            continue

        if dedupe_key in imported_keys:
            skipped_duplicate += 1
            continue

        sales_db.insert(sale_payload)
        imported_keys.add(dedupe_key)
        existing_by_key[dedupe_key] = sale_payload
        if to_int_amount(sale_payload.get("sale_price"), default=0) <= 0:
            provisional_by_sku_date[(sku, sale_date)] = sale_payload
        inserted += 1

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped_duplicate": skipped_duplicate,
        "skipped_invalid": skipped_invalid,
    }


def sync_purchase_status_from_sales(sales_db: Any, purchase_db: Any) -> Dict[str, int]:
    """販売数量に応じて仕入ステータスを販売済み / 一部販売済みにする。"""
    summary = {
        "updated_sold": 0,
        "updated_partial": 0,
        "unchanged": 0,
        "target_skus": 0,
    }
    try:
        sales = sales_db.list_all()
    except Exception:
        return summary

    sold_qty_by_sku: Dict[str, int] = {}
    for sale in sales:
        sku = normalize_text(sale.get("sku"))
        if not sku or not _countable_tx(sale):
            continue
        sold_qty_by_sku[sku] = sold_qty_by_sku.get(sku, 0) + to_int_count(sale.get("quantity"), default=1)

    summary["target_skus"] = len(sold_qty_by_sku)
    if not sold_qty_by_sku:
        return summary

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for sku, sold_qty in sold_qty_by_sku.items():
        purchase = purchase_db.get_by_sku(sku)
        if not purchase:
            continue
        purchase_qty = to_int_count(purchase.get("quantity"), default=1)
        current_status = normalize_text(purchase.get("status")).lower() or "ready"
        if current_status in _STATUS_SKIP_SALES:
            summary["unchanged"] += 1
            continue
        next_status = None
        reason = ""
        if sold_qty >= purchase_qty:
            next_status = "sold"
            reason = f"販売連動: 販売数 {sold_qty} / 仕入数 {purchase_qty}"
        elif sold_qty > 0:
            next_status = "partially_sold"
            reason = f"販売連動: 販売数 {sold_qty} / 仕入数 {purchase_qty}（在庫残あり）"
        if not next_status or current_status == next_status:
            summary["unchanged"] += 1
            continue
        purchase_db.upsert(
            {
                "sku": sku,
                "status": next_status,
                "status_reason": reason,
                "status_set_at": now_str,
            }
        )
        if next_status == "sold":
            summary["updated_sold"] += 1
        elif next_status == "partially_sold":
            summary["updated_partial"] += 1
    return summary


def apply_refunds_to_sales_db(sales_db: Any, refunds: List[Dict[str, Any]]) -> Dict[str, int]:
    """返品・返金を販売DBの返金総額と利益へ反映する。"""
    summary = {"matched": 0, "updated": 0, "unchanged": 0, "unmatched": 0}
    if not refunds:
        return summary
    sales = sales_db.list_all()
    by_key: Dict[tuple, Dict[str, Any]] = {}
    for sale in sales:
        order_id = normalize_text(sale.get("order_id"))
        sku = normalize_text(sale.get("sku"))
        if order_id and sku:
            by_key[(order_id, sku)] = sale
    for refund in refunds:
        order_id = normalize_text(refund.get("order_id"))
        sku = normalize_text(refund.get("sku"))
        sale = by_key.get((order_id, sku))
        if not sale:
            summary["unmatched"] += 1
            continue
        summary["matched"] += 1
        before = to_int_amount(sale.get("refund_total"), default=0)
        updated = apply_refund_to_sale(dict(sale), refund)
        after = to_int_amount(updated.get("refund_total"), default=0)
        if after == before and updated.get("net_profit") == sale.get("net_profit"):
            summary["unchanged"] += 1
            continue
        sale_id = sale.get("id")
        if not sale_id:
            summary["unchanged"] += 1
            continue
        sales_db.update(
            int(sale_id),
            {
                "refund_total": updated.get("refund_total"),
                "net_profit": updated.get("net_profit"),
            },
        )
        by_key[(order_id, sku)] = {**sale, **updated}
        summary["updated"] += 1
    return summary


def sale_line_fully_refunded(sale: Mapping[str, Any]) -> bool:
    """行の販売価格以上が返金されていれば、その販売は全額返金。"""
    price = to_int_amount(sale.get("sale_price"), default=0)
    refund = to_int_amount(sale.get("refund_total"), default=0)
    return price > 0 and refund >= price


def sku_sales_fully_refunded(sales: List[Mapping[str, Any]]) -> bool:
    """数える販売が1件以上あり、金額のある行がすべて全額返金なら True。"""
    countable = [sale for sale in sales if _countable_tx(sale)]
    if not countable:
        return False
    priced = [sale for sale in countable if to_int_amount(sale.get("sale_price"), default=0) > 0]
    if not priced or len(priced) != len(countable):
        return False
    return all(sale_line_fully_refunded(sale) for sale in priced)


def sync_refunded_purchase_status(sales_db: Any, purchase_db: Any) -> Dict[str, int]:
    """販売がすべて返金されたSKUだけ、仕入ステータスを返金にする。"""
    summary = {"updated_refunded": 0, "unchanged": 0}
    try:
        sales = sales_db.list_all()
    except Exception:
        return summary
    by_sku: Dict[str, List[Dict[str, Any]]] = {}
    for sale in sales:
        sku = normalize_text(sale.get("sku"))
        if sku:
            by_sku.setdefault(sku, []).append(sale)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for sku, rows in by_sku.items():
        if not sku_sales_fully_refunded(rows):
            summary["unchanged"] += 1
            continue
        purchase = purchase_db.get_by_sku(sku)
        if not purchase:
            summary["unchanged"] += 1
            continue
        current = normalize_text(purchase.get("status")).lower() or "ready"
        if current in _STATUS_SKIP_REFUND or current == "refunded":
            summary["unchanged"] += 1
            continue
        purchase_db.upsert(
            {
                "sku": sku,
                "status": "refunded",
                "status_reason": "返品連動: 販売がすべて返金",
                "status_set_at": now_str,
            }
        )
        summary["updated_refunded"] += 1
    return summary


def purchases_by_sku_for_sales(
    snapshot_rows: Optional[List[Mapping[str, Any]]] = None,
    db_rows: Optional[List[Mapping[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """手数料計算用に SKU → 仕入レコードを作る。スナップショットを優先し、DBで補う。"""
    by_sku: Dict[str, Dict[str, Any]] = {}
    for rec in snapshot_rows or []:
        if not isinstance(rec, Mapping):
            continue
        sku = normalize_text(rec.get("SKU") or rec.get("sku"))
        if sku and sku not in by_sku:
            by_sku[sku] = dict(rec)
    for row in db_rows or []:
        sku = normalize_text(row.get("sku"))
        if not sku:
            continue
        if sku not in by_sku:
            by_sku[sku] = {
                "sku": sku,
                "SKU": sku,
                "id": row.get("id"),
                "仕入れ価格": row.get("purchase_price") or 0,
                "purchase_price": row.get("purchase_price") or 0,
            }
            continue
        rec = by_sku[sku]
        if not rec.get("id") and row.get("id"):
            rec = {**rec, "id": row.get("id")}
        has_cost = False
        for key in ("仕入れ価格", "仕入価格", "purchase_price", "cost"):
            if rec.get(key) not in (None, "", 0, "0"):
                has_cost = True
                break
        if not has_cost and row.get("purchase_price") not in (None, "", 0):
            rec = {
                **rec,
                "仕入れ価格": row.get("purchase_price"),
                "purchase_price": row.get("purchase_price"),
            }
        by_sku[sku] = rec
    return by_sku


def load_latest_purchase_snapshot_rows() -> List[Dict[str, Any]]:
    """商品DBスナップショットの最新の非空データを返す。無ければ空。"""
    try:
        from database.product_purchase_db import ProductPurchaseDatabase
    except ImportError:
        from desktop.database.product_purchase_db import ProductPurchaseDatabase  # type: ignore
    db = ProductPurchaseDatabase()
    try:
        for row in db.list_snapshots():
            if int(row.get("item_count") or 0) <= 0:
                continue
            snapshot = db.get_snapshot(row["id"])
            data = (snapshot or {}).get("data") or []
            if data:
                return list(data)
    finally:
        db.close()
    return []


def sync_sales_from_client(
    client: Any,
    sales_db: Any,
    purchase_db: Any,
    *,
    days: int = 2,
    on_progress: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """注文を販売DBへ入れ、仕入ステータスを販売済み連動する。"""
    result = fetch_sale_payloads_from_sp_api(
        client,
        days=days,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    purchases = purchases_by_sku_for_sales(
        load_latest_purchase_snapshot_rows(),
        purchase_db.list_all(),
    )
    payloads = enrich_sales_with_purchase_fees(list(result.get("sales") or []), purchases)
    upsert = upsert_sales_payloads(sales_db, payloads)
    status = sync_purchase_status_from_sales(sales_db, purchase_db)
    return {"fetch": result, "upsert": upsert, "status": status}


def sync_refunds_from_client(
    client: Any,
    sales_db: Any,
    purchase_db: Any,
    *,
    days: int = 14,
    on_progress: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """返品を販売DBへ反映し、全額返金の仕入を返金ステータスにする。"""
    result = fetch_refund_records_from_sp_api(
        client,
        days=days,
        should_cancel=should_cancel,
        on_progress=on_progress,
    )
    applied = apply_refunds_to_sales_db(sales_db, list(result.get("refunds") or []))
    refunded = sync_refunded_purchase_status(sales_db, purchase_db)
    return {"fetch": result, "applied": applied, "refunded": refunded}
