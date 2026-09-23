# -*- coding: utf-8 -*-
"""確定済み仕入から、ルート日付と店舗コードが一致する行を読む。書き込まない。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from route_web.desktop_bridge import ensure_desktop_importable


def _date_key(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))[:8]
    if len(digits) != 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _store_codes(doc: Dict[str, Any]) -> Set[str]:
    codes: Set[str] = set()
    for store in doc.get("stores") or []:
        if not isinstance(store, dict):
            continue
        code = str(store.get("store_code") or "").strip().upper()
        if code:
            codes.add(code)
    return codes


def list_route_purchases(doc: Dict[str, Any], *, db_path: str | None = None) -> List[Dict[str, Any]]:
    ensure_desktop_importable()
    from database.product_db import ProductDatabase
    from database.purchase_db import PurchaseDatabase

    route_date = _date_key(doc.get("route_date"))
    codes = _store_codes(doc)
    if not route_date or not codes:
        return []

    products = ProductDatabase(db_path)
    purchases = PurchaseDatabase(db_path)
    product_by_sku: Dict[str, Dict[str, Any]] = {}
    cur = products.conn.cursor()
    cur.execute("SELECT sku, jan, product_name, purchase_date, store_code, store_name FROM products")
    for row in cur.fetchall():
        item = dict(row)
        sku = str(item.get("sku") or "").strip()
        if sku:
            product_by_sku[sku] = item

    found: List[Dict[str, Any]] = []
    seen = set()
    pcur = purchases.conn.cursor()
    pcur.execute("SELECT sku, purchase_date, store_code, store_name FROM purchases")
    for row in pcur.fetchall():
        item = dict(row)
        if _date_key(item.get("purchase_date")) != route_date:
            continue
        code = str(item.get("store_code") or "").strip().upper()
        if code not in codes:
            continue
        sku = str(item.get("sku") or "").strip()
        product = product_by_sku.get(sku) or {}
        jan = re.sub(r"\D", "", str(product.get("jan") or ""))
        key = (sku, code, jan)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "sku": sku,
                "jan": jan,
                "product_name": str(product.get("product_name") or "").strip(),
                "store_code": code,
                "store_name": str(item.get("store_name") or product.get("store_name") or "").strip(),
                "purchase_date": route_date,
            }
        )

    if found:
        try:
            products.close()
            purchases.close()
        except Exception:
            pass
        return found

    for product in product_by_sku.values():
        if _date_key(product.get("purchase_date")) != route_date:
            continue
        code = str(product.get("store_code") or "").strip().upper()
        if code not in codes:
            continue
        sku = str(product.get("sku") or "").strip()
        jan = re.sub(r"\D", "", str(product.get("jan") or ""))
        key = (sku, code, jan)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "sku": sku,
                "jan": jan,
                "product_name": str(product.get("product_name") or "").strip(),
                "store_code": code,
                "store_name": str(product.get("store_name") or "").strip(),
                "purchase_date": route_date,
            }
        )
    try:
        products.close()
        purchases.close()
    except Exception:
        pass
    return found
