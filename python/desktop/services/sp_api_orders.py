#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API Orders から販売DB用レコードを組み立てる。

- 注文一覧: Orders API getOrders
- 明細: getOrderItems（SKU・数量・ItemPrice）
- 手数料は Orders API に含まれないため、仕入DBの手数料・仕入値から利益を算出する
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from services.purchase_cost_calc import read_fee_fields, to_float
except ImportError:
    from desktop.services.purchase_cost_calc import read_fee_fields, to_float  # type: ignore

# 販売済み連動の対象にする注文ステータス（Canceled / Pending は除外）
DEFAULT_ORDER_STATUSES: tuple[str, ...] = (
    "Unshipped",
    "PartiallyShipped",
    "Shipped",
    "InvoiceUnconfirmed",
)

# 仕入 status 連動で「売れた」と数える transaction_method（小文字）
SALE_COUNTABLE_TX_METHODS = frozenset(
    {
        "",
        "shipped",
        "unshipped",
        "partiallyshipped",
        "partially_shipped",
        "invoiceunconfirmed",
    }
)


def _ensure_shared_on_path() -> Optional[Path]:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "shared" / "sp_api_client.py"
        if candidate.exists():
            shared = parent / "shared"
            shared_str = str(shared)
            if shared_str not in sys.path:
                sys.path.insert(0, shared_str)
            return shared
    return None


def build_sp_api_client():
    """shared の SpApiClient を生成する。"""
    if _ensure_shared_on_path() is None:
        raise RuntimeError("D:/HIRIO/shared/sp_api_client.py が見つかりません。")
    from sp_api_client import SpApiClient  # noqa: WPS433

    return SpApiClient()


def created_after_iso(*, days: int = 30) -> str:
    """現在から days 日前の UTC ISO8601（Orders API 用）。"""
    days = max(1, min(180, int(days)))
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_sale_date(raw: str) -> str:
    """
    PurchaseDate を販売DB向け `YYYY-MM-DD HH:MM:SS`（日本時間）にする。
    時刻が無い場合は日付のみ。
    """
    text = str(raw or "").strip()
    if not text:
        return ""

    # すでに CSV 形式ならそのまま正規化
    if " " in text and "T" not in text:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    try:
        # 2026-07-15T11:23:45.000Z / +00:00 など
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        jst = timezone(timedelta(hours=9))
        local = dt.astimezone(jst)
        return local.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    # 日付のみ
    if "T" in text:
        text = text.split("T", 1)[0]
    normalized = text.replace(".", "-").replace("/", "-")[:10]
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _money_amount(node: Any) -> int:
    if not isinstance(node, dict):
        return 0
    raw = node.get("Amount")
    if raw is None:
        return 0
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return 0


def _payload_dict(body: Dict[str, Any]) -> Dict[str, Any]:
    payload = body.get("payload")
    if isinstance(payload, dict):
        return payload
    return body if isinstance(body, dict) else {}


def extract_orders_page(body: Dict[str, Any]) -> tuple[List[Dict[str, Any]], str]:
    """getOrders レスポンスから注文リストと NextToken を取り出す。"""
    payload = _payload_dict(body)
    orders = payload.get("Orders")
    if not isinstance(orders, list):
        orders = []
    next_token = str(payload.get("NextToken") or "").strip()
    return [o for o in orders if isinstance(o, dict)], next_token


def extract_order_items_page(body: Dict[str, Any]) -> tuple[List[Dict[str, Any]], str]:
    """getOrderItems レスポンスから明細リストと NextToken を取り出す。"""
    payload = _payload_dict(body)
    items = payload.get("OrderItems")
    if not isinstance(items, list):
        items = []
    next_token = str(payload.get("NextToken") or "").strip()
    return [i for i in items if isinstance(i, dict)], next_token


def sales_method_from_order(order: Dict[str, Any]) -> str:
    channel = str(order.get("FulfillmentChannel") or "").upper()
    if channel == "AFN":
        return "FBA"
    if channel == "MFN":
        return "自己発送"
    return channel or "FBA"


def transaction_method_from_order(order: Dict[str, Any]) -> str:
    """仕入連動用。出荷済み扱いにできるステータスはそのまま返す。"""
    status = str(order.get("OrderStatus") or "").strip()
    return status or "Shipped"


def order_item_to_sale_payload(
    order: Dict[str, Any],
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """注文1件＋明細1行 → sales テーブル用 dict。SKU が無ければ None。"""
    sku = str(item.get("SellerSKU") or "").strip()
    if not sku:
        return None

    order_id = str(order.get("AmazonOrderId") or "").strip()
    sale_date = format_sale_date(str(order.get("PurchaseDate") or ""))
    if not sale_date:
        return None

    qty_raw = item.get("QuantityOrdered")
    try:
        quantity = int(qty_raw) if qty_raw is not None else 1
    except (TypeError, ValueError):
        quantity = 1
    if quantity <= 0:
        return None

    # ItemPrice は行合計（単価×数量）
    sale_price = _money_amount(item.get("ItemPrice"))
    title = str(item.get("Title") or "").strip()

    return {
        "sku": sku,
        "sale_date": sale_date,
        "sales_method": sales_method_from_order(order),
        "platform": "Amazon",
        "sale_price": sale_price,
        "quantity": quantity,
        "title": title,
        "platform_fee": 0,
        "shipping_fee": 0,
        "fba_fee": 0,
        "storage_fee": 0,
        "other_fees": 0,
        "refund_total": 0,
        "net_profit": None,
        "order_id": order_id,
        "buyer_name": "",
        "transaction_method": transaction_method_from_order(order),
    }


def _purchase_unit_cost(purchase: Mapping[str, Any]) -> int:
    for key in ("仕入れ価格", "仕入価格", "purchase_price", "cost"):
        if key in purchase and purchase.get(key) not in (None, ""):
            try:
                return int(round(to_float(purchase.get(key), 0.0)))
            except Exception:  # noqa: BLE001
                continue
    return 0


def apply_purchase_fees_to_sale(
    sale: Dict[str, Any],
    purchase: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """
    仕入DBの手数料・出荷費用・仕入値から販売行の手数料と利益を埋める。

    利益 = 販売価格 - プラットフォーム手数料 - 出荷費用 - 仕入れ価格×数量
    （仕入側の手数料は1個あたり想定のため、数量で掛ける）
    """
    if not purchase:
        return sale

    platform, shipping, _total = read_fee_fields(purchase)
    try:
        qty = int(sale.get("quantity") or 1)
    except (TypeError, ValueError):
        qty = 1
    qty = max(1, qty)

    platform_fee = int(round(float(platform or 0) * qty))
    shipping_fee = int(round(float(shipping or 0) * qty))
    unit_cost = _purchase_unit_cost(purchase)
    purchase_cost = unit_cost * qty
    sale_price = int(round(to_float(sale.get("sale_price"), 0.0)))

    if int(sale.get("platform_fee") or 0) <= 0 and platform_fee > 0:
        sale["platform_fee"] = platform_fee
    if int(sale.get("shipping_fee") or 0) <= 0 and shipping_fee > 0:
        sale["shipping_fee"] = shipping_fee

    pf = int(sale.get("platform_fee") or 0)
    sh = int(sale.get("shipping_fee") or 0)
    fba = int(sale.get("fba_fee") or 0)
    storage = int(sale.get("storage_fee") or 0)
    other = int(sale.get("other_fees") or 0)

    if sale_price > 0:
        sale["net_profit"] = sale_price - pf - sh - fba - storage - other - purchase_cost
    else:
        sale["net_profit"] = None

    purchase_id = purchase.get("id") or purchase.get("purchase_id")
    if purchase_id and not sale.get("purchase_id"):
        try:
            sale["purchase_id"] = int(purchase_id)
        except (TypeError, ValueError):
            pass

    return sale


def enrich_sales_with_purchase_fees(
    sales: List[Dict[str, Any]],
    purchases_by_sku: Mapping[str, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """SKU で仕入を引き、各販売行へ手数料・利益を反映する。"""
    out: List[Dict[str, Any]] = []
    for sale in sales:
        sku = str(sale.get("sku") or "").strip()
        purchase = purchases_by_sku.get(sku)
        out.append(apply_purchase_fees_to_sale(dict(sale), purchase))
    return out


def iter_all_orders(
    client: Any,
    *,
    created_after: str,
    order_statuses: Sequence[str] = DEFAULT_ORDER_STATUSES,
    sleep_sec: float = 1.0,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Iterable[Dict[str, Any]]:
    """ページネーションしながら注文を yield する。"""
    next_token: Optional[str] = None
    first = True
    while True:
        if should_cancel and should_cancel():
            return
        if not first and sleep_sec > 0:
            time.sleep(sleep_sec)
        first = False
        body = client.get_orders(
            created_after=created_after if not next_token else None,
            order_statuses=list(order_statuses) if not next_token else None,
            next_token=next_token,
        )
        orders, next_token = extract_orders_page(body)
        for order in orders:
            yield order
        if not next_token:
            return


def fetch_order_items(
    client: Any,
    order_id: str,
    *,
    sleep_sec: float = 0.5,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    """1注文の全明細を取得する。"""
    items: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    first = True
    while True:
        if should_cancel and should_cancel():
            break
        if not first and sleep_sec > 0:
            time.sleep(sleep_sec)
        first = False
        body = client.get_order_items(order_id, next_token=next_token)
        page, next_token = extract_order_items_page(body)
        items.extend(page)
        if not next_token:
            break
    return items


def fetch_sale_payloads_from_sp_api(
    client: Any,
    *,
    days: int = 30,
    order_statuses: Sequence[str] = DEFAULT_ORDER_STATUSES,
    sleep_sec: float = 1.0,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    SP-API から販売DB用レコード一覧を取得する。

    Returns:
        dict: sales(list), orders_seen(int), errors(list[str]), canceled(bool)
    """
    created_after = created_after_iso(days=days)
    sales: List[Dict[str, Any]] = []
    errors: List[str] = []
    orders_seen = 0
    canceled = False

    for order in iter_all_orders(
        client,
        created_after=created_after,
        order_statuses=order_statuses,
        sleep_sec=sleep_sec,
        should_cancel=should_cancel,
    ):
        if should_cancel and should_cancel():
            canceled = True
            break
        orders_seen += 1
        order_id = str(order.get("AmazonOrderId") or "").strip()
        if on_progress:
            on_progress(f"注文取得中… {orders_seen} 件目 ({order_id or '—'})")
        if not order_id:
            continue
        try:
            items = fetch_order_items(
                client,
                order_id,
                sleep_sec=max(0.3, sleep_sec * 0.5),
                should_cancel=should_cancel,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{order_id}: {exc}")
            continue
        if should_cancel and should_cancel():
            canceled = True
            break
        for item in items:
            payload = order_item_to_sale_payload(order, item)
            if payload:
                sales.append(payload)

    return {
        "sales": sales,
        "orders_seen": orders_seen,
        "errors": errors,
        "canceled": canceled,
        "created_after": created_after,
    }
