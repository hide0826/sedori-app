# -*- coding: utf-8 -*-
"""確定済み仕入から、ルートの商品候補を読む。書き込まない。"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from route_web.desktop_bridge import ensure_desktop_importable

# 指定ルートの日付から、この日数以内を「近い」とする。無ければもっと遠いルートも少し出す。
_NEAR_DAYS = 21
_NEAR_LIMIT = 5
_FAR_LIMIT = 3
_PRODUCTS_PER_ROUTE = 80


def _date_key(value: Any) -> str:
    """2026-09-19 や 2026/9/19 17:26 を 2026-09-19 にする。"""
    text = str(value or "").strip()
    if not text:
        return ""
    matched = re.match(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", text)
    if matched:
        year, month, day = int(matched.group(1)), int(matched.group(2)), int(matched.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def _sku_place(sku: str) -> Tuple[str, str]:
    """SKU先頭の日付と店舗コード。例: 20260919-BO-04-6600-6P-001"""
    matched = re.match(r"^(\d{8})-([A-Za-z]{1,6}-\d+)\b", str(sku or "").strip())
    if not matched:
        return "", ""
    return _date_key(matched.group(1)), matched.group(2).upper()


def _place(item: Dict[str, Any], product: Dict[str, Any]) -> Tuple[str, str, str]:
    """日付と店舗。列が空ならSKUから取る。"""
    sku = str(item.get("sku") or product.get("sku") or "").strip()
    sku_date, sku_code = _sku_place(sku)
    date = (
        _date_key(item.get("purchase_date"))
        or _date_key(product.get("purchase_date"))
        or sku_date
    )
    code = str(item.get("store_code") or product.get("store_code") or "").strip().upper() or sku_code
    return sku, date, code


def _doc_route(doc: Dict[str, Any]) -> Dict[str, str]:
    return {
        "route_name": str(doc.get("route_name") or "").strip(),
        "route_code": str(doc.get("route_code") or "").strip(),
        "route_date": _date_key(doc.get("route_date")),
    }


def _is_online_box(doc: Dict[str, Any]) -> bool:
    kind = str(doc.get("box_kind") or "").strip().lower()
    if kind == "online":
        return True
    return str(doc.get("route_code") or "").strip().upper() == "NET"


def _list_online_photo_candidates(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ネット箱は店舗コードではなく photo_candidates から候補を返す。"""
    ensure_desktop_importable()
    try:
        from services.online_box import load_photo_candidates
    except ImportError:
        from desktop.services.online_box import load_photo_candidates  # type: ignore

    route_meta = _doc_route(doc)
    rows = load_photo_candidates(doc=doc)
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku") or "").strip()
        jan = _jan_key(item.get("jan"))
        asin = _asin_key(item.get("asin"))
        name = str(item.get("product_name") or "").strip()
        key = (sku, jan, asin, name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "sku": sku,
                "jan": jan,
                "asin": asin,
                "product_name": name,
                "store_code": str(item.get("store_code") or "NET").strip() or "NET",
                "store_name": str(item.get("store_name") or "ネット仕入").strip(),
                "purchase_date": _date_key(item.get("purchase_date")) or route_meta["route_date"],
                "route_name": route_meta["route_name"] or str(item.get("route_name") or ""),
                "route_code": route_meta["route_code"] or "NET",
                "route_date": route_meta["route_date"],
            }
        )
    return out


def _jan_key(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _asin_key(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()[:16]


def _jan_equal(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) == 12 and right == "0" + left:
        return True
    if len(right) == 12 and left == "0" + right:
        return True
    return False


def _parse_date(value: str):
    if len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _latest_snapshot_rows(db_path: Optional[str]) -> List[Dict[str, Any]]:
    """画面の仕入DB（最新スナップショット）。テスト用DBのときは読まない。"""
    if db_path is not None:
        return []
    ensure_desktop_importable()
    try:
        from database.product_purchase_db import ProductPurchaseDatabase
    except Exception:
        return []
    db = ProductPurchaseDatabase()
    try:
        chosen = None
        for row in db.list_snapshots():
            if int(row.get("item_count") or 0) > 0:
                chosen = db.get_snapshot(int(row["id"]))
                break
        data = (chosen or {}).get("data") or []
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            return []
        found: List[Dict[str, Any]] = []
        for record in data:
            if not isinstance(record, dict):
                continue
            sku = str(record.get("SKU") or record.get("sku") or "").strip()
            if not sku:
                continue
            found.append(
                {
                    "sku": sku,
                    "jan": record.get("JAN") if record.get("JAN") not in (None, "") else record.get("jan") or "",
                    "asin": record.get("ASIN") or record.get("asin") or "",
                    "product_name": str(record.get("商品名") or record.get("product_name") or "").strip(),
                    "purchase_date": record.get("仕入日") or record.get("purchase_date") or "",
                    "store_code": str(record.get("仕入先") or record.get("store_code") or "").strip(),
                    "store_name": str(record.get("都道府県") or record.get("store_name") or "").strip(),
                }
            )
        return found
    except Exception:
        return []
    finally:
        try:
            db.close()
        except Exception:
            pass


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
    if _is_online_box(doc):
        return _list_online_photo_candidates(doc)

    ensure_desktop_importable()
    from database.product_db import ProductDatabase
    from database.purchase_db import PurchaseDatabase

    route_date = _date_key(doc.get("route_date"))
    route_meta = _doc_route(doc)
    codes = _store_codes(doc)
    if not route_date or not codes:
        return []

    products = ProductDatabase(db_path)
    purchases = PurchaseDatabase(db_path)
    product_by_sku: Dict[str, Dict[str, Any]] = {}
    cur = products.conn.cursor()
    cur.execute("SELECT sku, jan, asin, product_name, purchase_date, store_code, store_name FROM products")
    for row in cur.fetchall():
        item = dict(row)
        sku = str(item.get("sku") or "").strip()
        if sku:
            product_by_sku[sku] = item

    found: List[Dict[str, Any]] = []
    seen = set()
    pcur = purchases.conn.cursor()
    pcur.execute("SELECT sku, purchase_date, store_code, store_name FROM purchases")
    purchase_items = list(_latest_snapshot_rows(db_path))
    purchase_items.extend(dict(row) for row in pcur.fetchall())
    for item in purchase_items:
        sku, date, code = _place(item, product_by_sku.get(str(item.get("sku") or "").strip()) or {})
        if date != route_date or code not in codes:
            continue
        product = product_by_sku.get(sku) or {}
        jan = _jan_key(item.get("jan") or product.get("jan"))
        asin = _asin_key(item.get("asin") or product.get("asin"))
        name = str(item.get("product_name") or product.get("product_name") or "").strip()
        key = (sku, code, jan)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "sku": sku,
                "jan": jan,
                "asin": asin,
                "product_name": name,
                "store_code": code,
                "store_name": str(item.get("store_name") or product.get("store_name") or "").strip(),
                "purchase_date": route_date,
                "route_name": route_meta["route_name"],
                "route_code": route_meta["route_code"],
                "route_date": route_date,
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
        sku, date, code = _place(product, product)
        if date != route_date or code not in codes:
            continue
        jan = re.sub(r"\D", "", str(product.get("jan") or ""))
        asin = _asin_key(product.get("asin"))
        key = (sku, code, jan)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "sku": sku,
                "jan": jan,
                "asin": asin,
                "product_name": str(product.get("product_name") or "").strip(),
                "store_code": code,
                "store_name": str(product.get("store_name") or "").strip(),
                "purchase_date": route_date,
                "route_name": route_meta["route_name"],
                "route_code": route_meta["route_code"],
                "route_date": route_date,
            }
        )
    try:
        products.close()
        purchases.close()
    except Exception:
        pass
    return found


def _close_quietly(*dbs: Any) -> None:
    for db in dbs:
        try:
            db.close()
        except Exception:
            pass


def _affiliated_routes(conn: sqlite3.Connection) -> Dict[str, Dict[str, str]]:
    """店舗コード → 所属ルート。店舗マスタが無いDBでは空。"""
    found: Dict[str, Dict[str, str]] = {}
    try:
        cur = conn.execute(
            "SELECT supplier_code, affiliated_route_name, route_code FROM stores"
        )
    except sqlite3.OperationalError:
        return found
    for row in cur.fetchall():
        item = dict(row)
        code = str(item.get("supplier_code") or "").strip().upper()
        name = str(item.get("affiliated_route_name") or "").strip()
        if not code or not name:
            continue
        raw_code = str(item.get("route_code") or "").strip()
        if "," in raw_code:
            raw_code = ""
        found[code] = {"route_name": name, "route_code": raw_code}
    return found


def _visit_groups(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """訪問履歴を、日付とルートごとにまとめる。"""
    try:
        cur = conn.execute(
            "SELECT route_date, route_code, route_name, store_code FROM route_visit_logs"
        )
        rows = [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []
    grouped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for item in rows:
        route_date = _date_key(item.get("route_date"))
        if not route_date:
            continue
        route_code = str(item.get("route_code") or "").strip()
        route_name = str(item.get("route_name") or "").strip()
        key = (route_date, route_code, route_name)
        group = grouped.get(key)
        if group is None:
            group = {
                "route_date": route_date,
                "route_code": route_code,
                "route_name": route_name,
                "store_codes": set(),
            }
            grouped[key] = group
        code = str(item.get("store_code") or "").strip().upper()
        if code:
            group["store_codes"].add(code)
    return list(grouped.values())


def _catalog_rows(db_path: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """仕入DBの全行と、訪問履歴のルート一覧。"""
    ensure_desktop_importable()
    from database.product_db import ProductDatabase
    from database.purchase_db import PurchaseDatabase

    products = ProductDatabase(db_path)
    purchases = PurchaseDatabase(db_path)
    try:
        product_by_sku: Dict[str, Dict[str, Any]] = {}
        cur = products.conn.cursor()
        cur.execute(
            "SELECT sku, jan, asin, product_name, purchase_date, store_code, store_name FROM products"
        )
        for row in cur.fetchall():
            item = dict(row)
            sku = str(item.get("sku") or "").strip()
            if sku:
                product_by_sku[sku] = item

        affiliation = _affiliated_routes(products.conn)
        visits = _visit_groups(products.conn)
        visit_by_store_date: Dict[Tuple[str, str], Dict[str, str]] = {}
        for group in visits:
            for code in group["store_codes"]:
                visit_by_store_date[(group["route_date"], code)] = {
                    "route_name": group["route_name"],
                    "route_code": group["route_code"],
                    "route_date": group["route_date"],
                }

        found: List[Dict[str, Any]] = []
        seen = set()

        def add_row(sku: str, product: Dict[str, Any], item: Dict[str, Any]) -> None:
            sku, purchase_date, code = _place(item, product)
            jan = _jan_key(item.get("jan") or product.get("jan"))
            asin = _asin_key(item.get("asin") or product.get("asin"))
            key = (sku, code, jan, asin, purchase_date)
            if key in seen:
                return
            seen.add(key)
            label = visit_by_store_date.get((purchase_date, code)) or affiliation.get(code) or {}
            found.append(
                {
                    "sku": sku,
                    "jan": jan,
                    "asin": asin,
                    "product_name": str(item.get("product_name") or product.get("product_name") or "").strip(),
                    "store_code": code,
                    "store_name": str(
                        item.get("store_name") or product.get("store_name") or ""
                    ).strip(),
                    "purchase_date": purchase_date,
                    "route_name": str(label.get("route_name") or "").strip(),
                    "route_code": str(label.get("route_code") or "").strip(),
                    "route_date": str(label.get("route_date") or purchase_date),
                }
            )

        added_skus: Set[str] = set()

        def add_once(sku: str, product: Dict[str, Any], item: Dict[str, Any]) -> None:
            before = len(found)
            add_row(sku, product, item)
            if len(found) > before:
                added_skus.add(sku)

        for record in _latest_snapshot_rows(db_path):
            add_once(str(record.get("sku") or ""), record, record)
        pcur = purchases.conn.cursor()
        pcur.execute("SELECT sku, purchase_date, store_code, store_name FROM purchases")
        for row in pcur.fetchall():
            item = dict(row)
            sku = str(item.get("sku") or "").strip()
            if sku in added_skus:
                continue
            add_once(sku, product_by_sku.get(sku) or {}, item)
        for sku, product in product_by_sku.items():
            if sku in added_skus:
                continue
            add_once(sku, product, product)
        return found, visits
    finally:
        _close_quietly(products, purchases)


def _same_visit(group: Dict[str, Any], current: Dict[str, str]) -> bool:
    if group.get("route_date") != current.get("route_date"):
        return False
    if current.get("route_code") and group.get("route_code"):
        return group.get("route_code") == current.get("route_code")
    if current.get("route_name") and group.get("route_name"):
        return group.get("route_name") == current.get("route_name")
    return True


def _nearby_from_visits(
    current: Dict[str, str],
    catalog: List[Dict[str, Any]],
    visits: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    anchor = _parse_date(current.get("route_date") or "")
    if anchor is None:
        return []
    ranked = []
    for group in visits:
        if _same_visit(group, current):
            continue
        day = _parse_date(group["route_date"])
        if day is None:
            continue
        distance = abs((day - anchor).days)
        ranked.append((distance, group))
    ranked.sort(key=lambda item: (item[0], item[1]["route_date"]))
    near = [item for item in ranked if item[0] <= _NEAR_DAYS][:_NEAR_LIMIT]
    if not near:
        near = ranked[:_FAR_LIMIT]
    out: List[Dict[str, Any]] = []
    for distance, group in near:
        codes = group["store_codes"]
        rows = [
            row
            for row in catalog
            if row.get("purchase_date") == group["route_date"]
            and (not codes or row.get("store_code") in codes)
        ]
        rows = rows[:_PRODUCTS_PER_ROUTE]
        if not rows:
            continue
        labeled = []
        for row in rows:
            copied = dict(row)
            copied["route_name"] = group["route_name"]
            copied["route_code"] = group["route_code"]
            copied["route_date"] = group["route_date"]
            labeled.append(copied)
        out.append(
            {
                "route_date": group["route_date"],
                "route_code": group["route_code"],
                "route_name": group["route_name"],
                "day_distance": distance,
                "purchases": labeled,
            }
        )
    return out


def _nearby_from_catalog(
    current: Dict[str, str],
    catalog: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """訪問履歴が無いとき、仕入日と所属ルートで近い一覧を作る。"""
    anchor = _parse_date(current.get("route_date") or "")
    if anchor is None:
        return []
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for row in catalog:
        route_date = str(row.get("route_date") or row.get("purchase_date") or "")
        route_name = str(row.get("route_name") or "").strip()
        route_code = str(row.get("route_code") or "").strip()
        if not route_date or not route_name:
            continue
        key = (route_date, route_code, route_name)
        grouped.setdefault(key, []).append(row)
    ranked = []
    for key, rows in grouped.items():
        group = {
            "route_date": key[0],
            "route_code": key[1],
            "route_name": key[2],
            "store_codes": set(),
        }
        if _same_visit(group, current):
            continue
        day = _parse_date(key[0])
        if day is None:
            continue
        ranked.append((abs((day - anchor).days), group, rows))
    ranked.sort(key=lambda item: (item[0], item[1]["route_date"]))
    near = [item for item in ranked if item[0] <= _NEAR_DAYS][:_NEAR_LIMIT]
    if not near:
        near = ranked[:_FAR_LIMIT]
    out = []
    for distance, group, rows in near:
        out.append(
            {
                "route_date": group["route_date"],
                "route_code": group["route_code"],
                "route_name": group["route_name"],
                "day_distance": distance,
                "purchases": rows[:_PRODUCTS_PER_ROUTE],
            }
        )
    return out


def nearby_route_products(
    doc: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """指定ルートの日付に近いルートの商品一覧。"""
    catalog, visits = _catalog_rows(db_path)
    current = _doc_route(doc)
    nearby = _nearby_from_visits(current, catalog, visits)
    if not nearby:
        nearby = _nearby_from_catalog(current, catalog)
    return nearby


def lookup_photo_jan(
    doc: Dict[str, Any],
    jan: str,
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """撮影したJANの候補。

    1. いま開いているルートの仕入
    2. 無ければ仕入DBの全体
    3. それでも無ければ、日付の近いルートの商品一覧
    """
    jan_s = _jan_key(jan)
    if not jan_s:
        return {
            "jan": "",
            "level": "none",
            "candidates": [],
            "nearby_routes": [],
            "message": "JANを読めませんでした",
        }

    route_rows = list_route_purchases(doc, db_path=db_path)
    hits = [row for row in route_rows if _jan_equal(str(row.get("jan") or ""), jan_s)]
    if hits:
        return {
            "jan": jan_s,
            "level": "route",
            "candidates": hits,
            "nearby_routes": [],
            "message": "このルートの仕入です",
        }

    catalog, _visits = _catalog_rows(db_path)
    hits = [row for row in catalog if _jan_equal(str(row.get("jan") or ""), jan_s)]
    if hits:
        return {
            "jan": jan_s,
            "level": "db",
            "candidates": hits,
            "nearby_routes": [],
            "message": "このルートには無いので、DB全体から探しました",
        }

    nearby = nearby_route_products(doc, db_path=db_path)
    if nearby:
        return {
            "jan": jan_s,
            "level": "nearby",
            "candidates": [],
            "nearby_routes": nearby,
            "message": "JANはDBにありません。日付の近いルートの商品です",
        }
    return {
        "jan": jan_s,
        "level": "none",
        "candidates": [],
        "nearby_routes": [],
        "message": "該当するJANはDBにありません",
    }
