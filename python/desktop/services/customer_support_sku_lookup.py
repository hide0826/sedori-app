#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SKUからカスタマー対応用の商品コンテキストを組み立てる。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from database.product_db import ProductDatabase
    from database.purchase_db import PurchaseDatabase
    from services.flea_market_record_utils import (
        extract_purchase_record_from_purchase_table,
        merge_record_image_paths_from_purchase_table,
        resolve_local_image_path,
        resolve_record_product_images_preserve_sources,
    )
except ImportError:
    from desktop.database.product_db import ProductDatabase  # type: ignore
    from desktop.database.purchase_db import PurchaseDatabase  # type: ignore
    from desktop.services.flea_market_record_utils import (  # type: ignore
        extract_purchase_record_from_purchase_table,
        merge_record_image_paths_from_purchase_table,
        resolve_local_image_path,
        resolve_record_product_images_preserve_sources,
    )


def _first_str(data: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _first_number(data: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        val = data.get(key)
        if val is None or val == "":
            continue
        try:
            return float(str(val).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _find_in_product_widget_records(product_widget: Any, sku: str) -> Optional[Dict[str, Any]]:
    if product_widget is None:
        return None
    sku_key = (sku or "").strip()
    if not sku_key:
        return None
    getter = getattr(product_widget, "_purchase_record_by_sku", None)
    if callable(getter):
        rec = getter(sku_key)
        if rec:
            return dict(rec)
    records = getattr(product_widget, "purchase_all_records", None) or []
    for record in records:
        r_sku = _first_str(record, "SKU", "sku")
        if r_sku == sku_key:
            return dict(record)
    return None


def _slot_has_image(record: Dict[str, Any], slot: int) -> bool:
    return bool(_first_str(record, f"画像{slot}", f"image_{slot}"))


def _set_image_slot(record: Dict[str, Any], slot: int, path: str) -> None:
    record[f"画像{slot}"] = path
    record[f"image_{slot}"] = path


def _fill_scalar_defaults(
    merged: Dict[str, Any],
    purchase_row: Optional[Dict[str, Any]],
    product_row: Optional[Dict[str, Any]],
) -> None:
    """仕入スナップショットに無い項目だけ DB から補完（画像は別処理）。"""
    if purchase_row:
        merged.setdefault("仕入れ価格", purchase_row.get("purchase_price"))
        merged.setdefault("purchase_price", purchase_row.get("purchase_price"))
        merged.setdefault("コメント", purchase_row.get("comment") or "")
        merged.setdefault("comment", purchase_row.get("comment") or "")
    if product_row:
        merged.setdefault("ASIN", product_row.get("asin") or "")
        merged.setdefault("asin", product_row.get("asin") or "")
        merged.setdefault("商品名", product_row.get("product_name") or "")
        merged.setdefault("product_name", product_row.get("product_name") or "")


def _fill_empty_image_slots(
    merged: Dict[str, Any],
    purchase_row: Optional[Dict[str, Any]],
    product_row: Optional[Dict[str, Any]],
) -> None:
    """空スロットのみ purchase_db / product_db から同一 SKU の画像を補完。"""
    for i in range(1, 7):
        if _slot_has_image(merged, i):
            continue
        path = ""
        if purchase_row:
            path = str(
                purchase_row.get(f"image_{i}")
                or purchase_row.get(f"image_url_{i}")
                or ""
            ).strip()
        if not path and product_row:
            path = str(product_row.get(f"image_{i}") or "").strip()
        if path:
            _set_image_slot(merged, i, path)


def _build_authoritative_purchase_record(
    product_widget: Any,
    sku_key: str,
) -> Optional[Dict[str, Any]]:
    """
    該当 SKU の仕入DB行を優先順位付きで取得する。
    1. 仕入DBテーブル（UserRole フルパス・ソート後も SKU で特定）
    2. purchase_all_records / master
    """
    table_record = extract_purchase_record_from_purchase_table(product_widget, sku_key)
    memory_record = _find_in_product_widget_records(product_widget, sku_key)

    if table_record and memory_record:
        merged = dict(memory_record)
        for key, value in table_record.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip() and key in merged:
                continue
            merged[key] = value
        return merged
    if table_record:
        return dict(table_record)
    if memory_record:
        return dict(memory_record)
    return None


def lookup_sku_context(
    sku: str,
    *,
    product_widget: Any = None,
    purchase_db: Optional[PurchaseDatabase] = None,
    product_db: Optional[ProductDatabase] = None,
) -> Optional[Dict[str, Any]]:
    """
    仕入DB・商品DB・仕入DBタブのメモリ上レコードから商品情報を統合して返す。
    同一 ASIN の別 SKU 画像を混ぜないよう、該当 SKU 行を最優先する。
    見つからない場合は None。
    """
    sku_key = (sku or "").strip()
    if not sku_key:
        return None

    purchase_db = purchase_db or PurchaseDatabase()
    product_db = product_db or ProductDatabase()

    purchase_record = _build_authoritative_purchase_record(product_widget, sku_key)
    purchase_row = purchase_db.get_by_sku(sku_key)
    product_row = product_db.get_by_sku(sku_key)

    if not purchase_record and not purchase_row and not product_row:
        return None

    merged: Dict[str, Any] = dict(purchase_record) if purchase_record else {}
    merged["SKU"] = sku_key
    merged["sku"] = sku_key

    _fill_scalar_defaults(merged, purchase_row, product_row)

    if product_widget is not None:
        merge_record_image_paths_from_purchase_table(merged, product_widget)

    resolve_record_product_images_preserve_sources(merged)
    _fill_empty_image_slots(merged, purchase_row, product_row)
    resolve_record_product_images_preserve_sources(merged)

    asin = _first_str(merged, "ASIN", "asin")
    product_name = _first_str(merged, "商品名", "product_name", "title")
    purchase_price = _first_number(merged, "仕入れ価格", "purchase_price", "仕入価格")
    planned_price = _first_number(merged, "販売予定価格", "planned_price", "price")
    shipping = _first_str(merged, "発送方法", "shipping_method", "shippingMethod")
    comment = _first_str(merged, "コメント", "comment")
    image_paths: List[Dict[str, Any]] = []
    for i in range(1, 7):
        raw = _first_str(merged, f"画像{i}", f"image_{i}")
        if not raw or raw.startswith(("http://", "https://")):
            continue
        resolved = resolve_local_image_path(raw, merged) or raw
        path_obj = Path(resolved)
        if path_obj.is_file():
            image_paths.append(
                {
                    "slot": i,
                    "path": str(path_obj.resolve()),
                    "label": path_obj.name,
                }
            )

    return {
        "sku": sku_key,
        "asin": asin,
        "product_name": product_name,
        "purchase_price": int(purchase_price) if purchase_price is not None else None,
        "planned_price": int(planned_price) if planned_price is not None else None,
        "shipping_method": shipping,
        "comment": comment,
        "image_paths": image_paths,
        "raw": merged,
    }


def format_sku_context_for_display(ctx: Dict[str, Any]) -> str:
    """商品情報パネル用の表示テキスト（画像は別リンク表示）。"""
    lines = [
        f"ASIN: {ctx.get('asin') or '（なし）'}",
        f"商品名: {ctx.get('product_name') or '（なし）'}",
        f"仕入れ価格: {_fmt_yen(ctx.get('purchase_price'))}",
        f"販売予定価格: {_fmt_yen(ctx.get('planned_price'))}",
        f"発送方法: {ctx.get('shipping_method') or '（なし）'}",
        f"コメント: {ctx.get('comment') or '（なし）'}",
    ]
    paths: List[Dict[str, Any]] = ctx.get("image_paths") or []
    if paths:
        lines.append(f"商品画像: {len(paths)}件（下の「商品画像」欄をクリック）")
    else:
        lines.append("商品画像: （なし）")
    return "\n".join(lines)


def _fmt_yen(value: Any) -> str:
    if value is None or value == "":
        return "（なし）"
    try:
        return f"{int(float(value)):,} 円"
    except (TypeError, ValueError):
        return str(value)
