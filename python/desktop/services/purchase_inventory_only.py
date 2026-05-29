#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在庫CSV専用SKU（仕入DBに無い／在庫専用ステータス）の登録・抽出ヘルパー。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

PURCHASE_STATUS_INVENTORY_ONLY = "inventory_only"
PURCHASE_STATUS_INVENTORY_ONLY_LABEL = "在庫専用"
PURCHASE_STATUS_REASON_INVENTORY_CSV = "在庫専用: 在庫CSVから登録"

SKU_COLUMN_CANDIDATES = frozenset({
    "sku", "sellersku", "merchantsku", "出品者sku", "出品sku", "商品sku", "商品管理番号",
})


def _norm_col_name(col: Any) -> str:
    return str(col).strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _find_column(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    if df is None or df.empty:
        return None
    norm_map = {_norm_col_name(c): c for c in df.columns}
    for name in candidates:
        key = _norm_col_name(name)
        if key in norm_map:
            return norm_map[key]
    return None


def _cell_text(raw_value: Any, *, as_sku: bool = False) -> str:
    if raw_value is None:
        return ""
    if isinstance(raw_value, float) and pd.isna(raw_value):
        return ""
    text = normalize_sku_from_cell(raw_value) if as_sku else str(raw_value).strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    if not as_sku and text.startswith('="') and text.endswith('"'):
        text = text[2:-1].strip()
    return text


def _cell_number(raw_value: Any) -> Optional[float]:
    text = _cell_text(raw_value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_purchase_date_from_sku(sku: str) -> str:
    """
    SKUから仕入れ日（YYYY/MM/DD）を推定する。

    対応形式:
    - 先頭8桁 YYYYMMDD … 20251220-used1-014
    - 先頭6桁 YYMMDD … 251026-2-040 → 2025/10/26
    - 文中の YYYYMMDD … hmk-20251115-used2-025
    """
    sku = str(sku or "").strip()
    if not sku:
        return ""

    def _fmt(date_str: str) -> str:
        try:
            return datetime.strptime(date_str, "%Y%m%d").strftime("%Y/%m/%d")
        except ValueError:
            return ""

    m8 = re.match(r"^(\d{8})(?:\D|$)", sku)
    if m8:
        result = _fmt(m8.group(1))
        if result:
            return result

    m6 = re.match(r"^(\d{6})(?:\D|$)", sku)
    if m6:
        result = _fmt(f"20{m6.group(1)}")
        if result:
            return result

    m_embedded = re.search(r"(20\d{6})", sku)
    if m_embedded:
        result = _fmt(m_embedded.group(1))
        if result:
            return result

    return ""


def backfill_purchase_date_from_sku(record: Dict[str, Any]) -> None:
    """仕入れ日が空のレコードに SKU から日付を補完（インプレース）。"""
    purchase_date = str(record.get("仕入れ日") or record.get("purchase_date") or "").strip()
    if purchase_date and purchase_date.lower() not in ("nan", "none"):
        return
    sku = str(record.get("SKU") or record.get("sku") or "").strip()
    inferred = parse_purchase_date_from_sku(sku)
    if inferred:
        record["仕入れ日"] = inferred
        record["purchase_date"] = inferred


def asin_from_record(record: Optional[Dict[str, Any]]) -> str:
    """表示レコード／DB行から ASIN を取得。"""
    if not record:
        return ""
    asin = str(record.get("ASIN") or record.get("asin") or "").strip()
    if asin.lower() in ("nan", "none"):
        return ""
    return asin


def is_purchase_data_incomplete(record: Optional[Dict[str, Any]]) -> bool:
    """SKUのみ登録（ASIN未入力）なら True。レコード無しも True。"""
    return not asin_from_record(record)


def is_inventory_only_status(status: Any) -> bool:
    return str(status or "").strip().lower() == PURCHASE_STATUS_INVENTORY_ONLY


def normalize_sku_from_cell(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    text = str(raw_value).strip()
    if not text or text.lower() in ("nan", "none"):
        return ""
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1].strip()
    return text


def find_sku_column(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty:
        return None

    def _norm(col: Any) -> str:
        return str(col).strip().lower().replace(" ", "").replace("_", "").replace("-", "")

    for col in df.columns:
        if _norm(col) in SKU_COLUMN_CANDIDATES:
            return col
    return None


def row_dict_from_inventory_csv(df: pd.DataFrame, row_index: int) -> Dict[str, Any]:
    """在庫CSVの1行から仕入DB登録用フィールドを抽出（改定実行CSV列に対応）。"""
    row = df.iloc[row_index]
    sku_col = find_sku_column(df)
    sku = _cell_text(row.get(sku_col), as_sku=True) if sku_col else ""

    def _pick_text(*names: str) -> str:
        col = _find_column(df, *names)
        return _cell_text(row.get(col)) if col else ""

    def _pick_number(*names: str) -> Optional[float]:
        col = _find_column(df, *names)
        return _cell_number(row.get(col)) if col else None

    asin = _pick_text("asin")
    title = _pick_text("title")
    price_raw = _pick_text("price")
    cost_raw = _pick_text("cost")
    number_raw = _pick_text("number", "add_number", "add-number")
    profit_raw = _pick_text("profit")
    amazon_fee_raw = _pick_text("amazon-fee", "amazon_fee", "amazonfee")
    shipping_raw = _pick_text("shipping-price", "shipping_price", "shipping")
    condition = _pick_text("condition", "コンディション")
    condition_note = _pick_text("conditionnote", "conditionNote", "コンディション説明")

    break_even_raw = _pick_text(
        "price-cost-amazon-fee",
        "price_cost_amazon_fee",
        "akaji",
        "損益分岐点",
        "breakeven",
    )
    if not break_even_raw:
        cost_num = _pick_number("cost")
        fee_num = _pick_number("amazon-fee", "amazon_fee", "amazonfee")
        if cost_num is not None and fee_num is not None:
            break_even_raw = str(int(round(cost_num + fee_num)))

    purchase_date = parse_purchase_date_from_sku(sku)

    return {
        "sku": sku,
        "SKU": sku,
        "ASIN": asin,
        "asin": asin,
        "商品名": title,
        "title": title,
        "price": price_raw,
        "cost": cost_raw,
        "number": number_raw,
        "profit": profit_raw,
        "amazon-fee": amazon_fee_raw,
        "shipping-price": shipping_raw,
        "akaji": break_even_raw,
        "仕入れ日": purchase_date,
        "purchase_date": purchase_date,
        "コンディション": condition,
        "condition": condition,
        "コンディション説明": condition_note,
        "conditionNote": condition_note,
    }


def extract_rows_not_in_purchase_db(
    df: pd.DataFrame,
    purchase_db: Any,
    *,
    display_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    在庫CSVから仕入DBへ登録・上書きすべき行を抽出（重複SKUは1件）。

    対象:
    - 仕入DB（表示スナップショット／hirio.db）に SKU が無い行
    - SKU はあるが ASIN が未入力の行（SKUのみ登録の上書き）
    """
    if df is None or df.empty or purchase_db is None:
        return []
    sku_col = find_sku_column(df)
    if not sku_col:
        return []

    display_by_sku: Dict[str, Dict[str, Any]] = {}
    for rec in display_records or []:
        sku_key = normalize_sku_from_cell(rec.get("SKU") or rec.get("sku"))
        if sku_key:
            display_by_sku[sku_key] = rec

    seen: Set[str] = set()
    missing: List[Dict[str, Any]] = []
    for i in range(len(df)):
        sku = normalize_sku_from_cell(df.iloc[i].get(sku_col))
        if not sku or sku in seen:
            continue
        seen.add(sku)

        db_row: Optional[Dict[str, Any]] = None
        try:
            db_row = purchase_db.get_by_sku(sku)
        except Exception:
            pass
        display_row = display_by_sku.get(sku)

        if display_row is not None:
            should_include = is_purchase_data_incomplete(display_row)
        elif db_row is not None:
            should_include = is_purchase_data_incomplete(db_row)
        else:
            should_include = True

        if not should_include:
            continue

        item = row_dict_from_inventory_csv(df, i)
        item["row_index"] = i
        item["overwrite"] = display_row is not None or db_row is not None
        missing.append(item)
    return missing


def _to_int_or_empty(value: Any) -> Any:
    if value is None or value == "":
        return ""
    try:
        return int(round(float(str(value).replace(",", "").strip())))
    except (TypeError, ValueError):
        return value


def build_inventory_only_display_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """在庫CSV行から仕入DBタブ表示用レコード（日本語列）を組み立てる。"""
    try:
        from desktop.services.purchase_cost_calc import (
            COL_PLATFORM_FEE,
            COL_SHIPPING,
            COL_TOTAL_COST,
            augment_purchase_cost_record,
            recalculate_profit_fields,
            to_float,
        )
    except ImportError:
        try:
            from services.purchase_cost_calc import (  # type: ignore
                COL_PLATFORM_FEE,
                COL_SHIPPING,
                COL_TOTAL_COST,
                augment_purchase_cost_record,
                recalculate_profit_fields,
                to_float,
            )
        except ImportError:
            from purchase_cost_calc import (  # type: ignore
                COL_PLATFORM_FEE,
                COL_SHIPPING,
                COL_TOTAL_COST,
                augment_purchase_cost_record,
                recalculate_profit_fields,
                to_float,
            )

    sku = str(row.get("sku") or row.get("SKU") or "").strip()
    purchase_date = str(
        row.get("仕入れ日") or row.get("purchase_date") or parse_purchase_date_from_sku(sku)
    ).strip()
    asin = str(row.get("ASIN") or row.get("asin") or "").strip()
    title = str(row.get("商品名") or row.get("title") or "").strip()
    quantity = _to_int_or_empty(row.get("number") or row.get("仕入れ個数") or row.get("quantity") or 1)
    purchase_price = _to_int_or_empty(row.get("cost") or row.get("仕入れ価格") or row.get("purchase_price"))
    planned_price = _to_int_or_empty(row.get("price") or row.get("販売予定価格") or row.get("planned_price"))
    expected_profit = _to_int_or_empty(row.get("profit") or row.get("見込み利益") or row.get("expected_profit"))
    amazon_fee = _to_int_or_empty(
        row.get("amazon-fee") or row.get("amazon_fee") or row.get(COL_PLATFORM_FEE)
    )
    shipping = _to_int_or_empty(
        row.get("shipping-price") or row.get("shipping_price") or row.get(COL_SHIPPING) or 0
    )
    break_even = _to_int_or_empty(
        row.get("akaji") or row.get("損益分岐点") or row.get("price-cost-amazon-fee")
    )

    raw_condition = str(row.get("コンディション") or row.get("condition") or "").strip()
    try:
        from desktop.services.condition_labels import normalize_condition_display
    except ImportError:
        try:
            from services.condition_labels import normalize_condition_display  # type: ignore
        except ImportError:
            from condition_labels import normalize_condition_display  # type: ignore
    condition_label = normalize_condition_display(raw_condition)
    condition_note = str(
        row.get("コンディション説明") or row.get("conditionNote") or row.get("condition_note") or ""
    ).strip()

    display: Dict[str, Any] = {
        "SKU": sku,
        "sku": sku,
        "仕入れ日": purchase_date,
        "purchase_date": purchase_date,
        "ASIN": asin,
        "asin": asin,
        "商品名": title,
        "title": title,
        "仕入れ個数": quantity or 1,
        "quantity": quantity or 1,
        "仕入れ価格": purchase_price,
        "purchase_price": purchase_price,
        "販売予定価格": planned_price,
        "planned_price": planned_price,
        "見込み利益": expected_profit,
        "expected_profit": expected_profit,
        COL_PLATFORM_FEE: amazon_fee,
        "amazon-fee": amazon_fee,
        COL_SHIPPING: shipping,
        COL_TOTAL_COST: amazon_fee,
        "費用合計": amazon_fee,
        "損益分岐点": break_even,
        "akaji": break_even,
        "コンディション": condition_label,
        "condition": condition_label,
        "コンディション説明": condition_note,
        "conditionNote": condition_note,
        "ステータス": PURCHASE_STATUS_INVENTORY_ONLY,
        "status": PURCHASE_STATUS_INVENTORY_ONLY,
        "ステータス理由": PURCHASE_STATUS_REASON_INVENTORY_CSV,
        "status_reason": PURCHASE_STATUS_REASON_INVENTORY_CSV,
        "status_set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "価格改定": "ON",
        "repricing_enabled": 1,
        "ladder_enabled": 0,
        "ladder_rules": "",
        "販売チャネル": "Amazon",
        "コメント": row.get("comment") or "inventory_csv_register",
    }

    pf = recalculate_profit_fields(
        to_float(purchase_price),
        to_float(planned_price),
        to_float(amazon_fee),
        to_float(shipping),
        to_float(amazon_fee),
        stored_profit=expected_profit,
        stored_break_even=break_even,
        prefer_stored_profit=bool(expected_profit),
        prefer_stored_break_even=bool(break_even),
    )
    if expected_profit:
        display["見込み利益"] = pf["見込み利益"]
        display["expected_profit"] = pf["見込み利益"]
    if break_even:
        display["損益分岐点"] = pf["損益分岐点"]
        display["akaji"] = pf["損益分岐点"]
    display[COL_TOTAL_COST] = pf[COL_TOTAL_COST]
    display["費用合計"] = pf[COL_TOTAL_COST]
    display["想定利益率"] = pf["想定利益率"]
    display["想定ROI"] = pf["想定ROI"]
    display["expected_margin"] = pf["想定利益率"]
    display["expected_roi"] = pf["想定ROI"]

    return augment_purchase_cost_record(display)


def merge_display_record_into_product_widget(
    product_widget: Any,
    display_record: Dict[str, Any],
    *,
    full_overwrite: bool = False,
) -> None:
    """仕入DBタブの内部リストへ表示レコードを追加または更新。"""
    if product_widget is None:
        return
    sku = str(display_record.get("SKU") or display_record.get("sku") or "").strip()
    if not sku:
        return
    for attr in ("purchase_all_records_master", "purchase_all_records", "purchase_records"):
        lst = getattr(product_widget, attr, None)
        if not isinstance(lst, list):
            continue
        updated = False
        for i, rec in enumerate(lst):
            rec_sku = str(rec.get("SKU") or rec.get("sku") or "").strip()
            if rec_sku == sku:
                if full_overwrite:
                    row_id = rec.get("_row_id")
                    merged = dict(display_record)
                    if row_id is not None:
                        merged["_row_id"] = row_id
                else:
                    merged = dict(rec)
                    merged.update(display_record)
                lst[i] = merged
                updated = True
                break
        if not updated:
            lst.append(dict(display_record))


def register_inventory_only_row(
    row: Dict[str, Any],
    purchase_db: Any,
    *,
    product_widget: Any = None,
    enable_repricing: bool = True,
    enable_ladder: bool = False,
    ladder_rules_json: str = "",
) -> Dict[str, Any]:
    """在庫専用SKUを hirio.db とスナップショット用表示レコードの両方に登録。"""
    display = build_inventory_only_display_record(row)
    payload = build_inventory_only_upsert_payload(
        display,
        enable_repricing=enable_repricing,
        enable_ladder=enable_ladder,
        ladder_rules_json=ladder_rules_json,
    )
    purchase_db.upsert(payload)
    full_overwrite = bool(row.get("overwrite"))
    merge_display_record_into_product_widget(
        product_widget, display, full_overwrite=full_overwrite
    )
    return display


def build_inventory_only_upsert_payload(
    row: Dict[str, Any],
    *,
    enable_repricing: bool = True,
    enable_ladder: bool = False,
    ladder_rules_json: str = "",
) -> Dict[str, Any]:
    sku = str(row.get("sku") or row.get("SKU") or "").strip()
    if not sku:
        raise ValueError("sku is required")

    purchase_date = str(
        row.get("仕入れ日") or row.get("purchase_date") or parse_purchase_date_from_sku(sku)
    ).strip()
    purchase_price = _to_int_or_empty(
        row.get("仕入れ価格") or row.get("purchase_price") or row.get("cost")
    )
    quantity = _to_int_or_empty(row.get("仕入れ個数") or row.get("quantity") or row.get("number") or 1)
    expected_margin = row.get("想定利益率") or row.get("expected_margin")
    expected_roi = row.get("想定ROI") or row.get("expected_roi")

    payload: Dict[str, Any] = {
        "sku": sku,
        "status": PURCHASE_STATUS_INVENTORY_ONLY,
        "status_reason": PURCHASE_STATUS_REASON_INVENTORY_CSV,
        "status_set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repricing_enabled": 1 if enable_repricing else 0,
        "ladder_enabled": 1 if enable_ladder else 0,
        "ladder_rules": ladder_rules_json or "",
        "comment": row.get("comment") or row.get("コメント") or "inventory_csv_register",
    }
    if purchase_date:
        payload["purchase_date"] = purchase_date
    if purchase_price != "":
        payload["purchase_price"] = purchase_price
    if quantity != "":
        payload["quantity"] = quantity or 1
    if expected_margin not in (None, ""):
        try:
            payload["expected_margin"] = float(expected_margin)
        except (TypeError, ValueError):
            pass
    if expected_roi not in (None, ""):
        try:
            payload["expected_roi"] = float(expected_roi)
        except (TypeError, ValueError):
            pass

    cond_note = str(
        row.get("コンディション説明")
        or row.get("conditionNote")
        or row.get("condition_note")
        or ""
    ).strip()
    if cond_note:
        payload["condition_note"] = cond_note
    try:
        from desktop.services.condition_labels import condition_code_from_value
    except ImportError:
        try:
            from services.condition_labels import condition_code_from_value  # type: ignore
        except ImportError:
            from condition_labels import condition_code_from_value  # type: ignore
    cond_code = condition_code_from_value(
        row.get("condition_code") or row.get("コンディション") or row.get("condition")
    )
    if cond_code is not None:
        payload["condition_code"] = cond_code
    return payload


def normalize_status_code(raw: Any) -> str:
    """表示ラベル・内部コードをフィルタ用コードに正規化。"""
    s = str(raw or "ready").strip().lower()
    if not s:
        return "ready"
    label_to_code = {
        "在庫専用": "inventory_only",
        "出品可能": "ready",
        "破損": "damaged",
        "登録不可": "unlistable",
        "保管中": "storage",
        "次回出品予定": "pending",
        "販売中": "selling",
        "一部販売済み": "partially_sold",
        "販売済み": "sold",
    }
    for label, code in label_to_code.items():
        if s == label.lower() or s == label:
            return code
    return s


def apply_purchase_db_fields_to_display_record(
    row: Dict[str, Any], db_row: Dict[str, Any]
) -> None:
    """仕入DB(hirio.db)の値を表示用レコードへ上書き（ステータス・TP・月別運用）。"""
    status = db_row.get("status")
    if status is not None and str(status).strip():
        row["ステータス"] = status
        row["status"] = status
    reason = db_row.get("status_reason")
    if reason is not None:
        row["ステータス理由"] = reason
        row["status_reason"] = reason
    for tp_key in ("tp0", "tp1", "tp2", "tp3"):
        val = db_row.get(tp_key)
        if val is not None and str(val).strip():
            row[tp_key] = val
            row[tp_key.upper()] = val
    le = db_row.get("ladder_enabled")
    if le is not None:
        row["ladder_enabled"] = le
    lr = db_row.get("ladder_rules")
    if lr is not None:
        row["ladder_rules"] = lr
    re = db_row.get("repricing_enabled")
    if re is not None:
        row["repricing_enabled"] = re
        row["価格改定"] = "OFF" if str(re).strip().lower() in ("0", "off", "false", "no") else "ON"
    pp = db_row.get("purchase_price")
    if pp is not None and str(pp).strip() and not row.get("仕入れ価格"):
        row["仕入れ価格"] = pp
        row["purchase_price"] = pp
    pd = db_row.get("purchase_date")
    if pd and not row.get("仕入れ日"):
        row["仕入れ日"] = pd
        row["purchase_date"] = pd
    qty = db_row.get("quantity")
    if qty is not None and str(qty).strip() and not row.get("仕入れ個数"):
        row["仕入れ個数"] = qty
        row["quantity"] = qty
    em = db_row.get("expected_margin")
    if em is not None and str(em).strip() and not row.get("想定利益率"):
        row["想定利益率"] = em
        row["expected_margin"] = em
    er = db_row.get("expected_roi")
    if er is not None and str(er).strip() and not row.get("想定ROI"):
        row["想定ROI"] = er
        row["expected_roi"] = er


def purchase_display_record_from_db_row(db_row: Dict[str, Any]) -> Dict[str, Any]:
    """仕入DB行を仕入DBタブ表示用レコードに変換（スナップショットに無い行の追加用）。"""
    rec = purchase_record_from_db_row(db_row)
    rec["仕入れ日"] = db_row.get("purchase_date") or rec.get("仕入れ日") or ""
    rec["purchase_date"] = rec["仕入れ日"]
    if not rec["仕入れ日"]:
        inferred = parse_purchase_date_from_sku(str(db_row.get("sku") or ""))
        if inferred:
            rec["仕入れ日"] = inferred
            rec["purchase_date"] = inferred
    rec["仕入れ個数"] = db_row.get("quantity") or 1
    rec["quantity"] = rec["仕入れ個数"]
    cn = db_row.get("condition_note")
    if cn:
        rec["コンディション説明"] = cn
        rec["condition_note"] = cn
    em = db_row.get("expected_margin")
    if em is not None and str(em).strip():
        rec["想定利益率"] = em
        rec["expected_margin"] = em
    er = db_row.get("expected_roi")
    if er is not None and str(er).strip():
        rec["想定ROI"] = er
        rec["expected_roi"] = er
    try:
        from desktop.services.purchase_cost_calc import augment_purchase_cost_record
    except ImportError:
        try:
            from services.purchase_cost_calc import augment_purchase_cost_record  # type: ignore
        except ImportError:
            from purchase_cost_calc import augment_purchase_cost_record  # type: ignore
    return augment_purchase_cost_record(rec)


def merge_purchase_history_db_into_display_records(
    records: List[Dict[str, Any]],
    purchase_db: Any,
    *,
    include_db_only_rows: bool = True,
) -> List[Dict[str, Any]]:
    """
    スナップショット由来レコードに hirio.db(purchases) をマージする。
    - 既存SKU: ステータス・TP・月別運用をDB優先で反映
    - DBのみ存在するSKU（在庫専用登録など）: 行を追加
    """
    out: List[Dict[str, Any]] = [dict(r) for r in (records or [])]
    index_by_sku: Dict[str, int] = {}
    for i, row in enumerate(out):
        sku = str(row.get("SKU") or row.get("sku") or "").strip()
        if sku:
            index_by_sku[sku] = i

    try:
        db_rows = purchase_db.list_all()
    except Exception as e:
        print(f"[merge_purchase_history_db] list_all failed: {e}")
        return out

    for db_row in db_rows:
        sku = str(db_row.get("sku") or "").strip()
        if not sku:
            continue
        if sku in index_by_sku:
            apply_purchase_db_fields_to_display_record(out[index_by_sku[sku]], db_row)
        elif include_db_only_rows:
            out.append(purchase_display_record_from_db_row(db_row))
            index_by_sku[sku] = len(out) - 1
    return out


def purchase_record_from_db_row(db_row: Dict[str, Any]) -> Dict[str, Any]:
    """仕入DB行を仕入行編集ダイアログ用レコードに変換。"""
    sku = str(db_row.get("sku") or "").strip()
    status = db_row.get("status") or PURCHASE_STATUS_INVENTORY_ONLY
    purchase_date = db_row.get("purchase_date") or parse_purchase_date_from_sku(sku)
    return {
        "SKU": sku,
        "sku": sku,
        "仕入れ日": purchase_date or "",
        "purchase_date": purchase_date or "",
        "ASIN": db_row.get("asin") or "",
        "商品名": db_row.get("product_name") or db_row.get("title") or "",
        "仕入れ個数": db_row.get("quantity") or 1,
        "quantity": db_row.get("quantity") or 1,
        "コンディション": db_row.get("condition_note") or "",
        "仕入れ価格": db_row.get("purchase_price") or 0,
        "purchase_price": db_row.get("purchase_price") or 0,
        "販売予定価格": db_row.get("planned_price") or 0,
        "見込み利益": db_row.get("expected_profit") or 0,
        "想定利益率": db_row.get("expected_margin") or "",
        "expected_margin": db_row.get("expected_margin") or "",
        "想定ROI": db_row.get("expected_roi") or "",
        "expected_roi": db_row.get("expected_roi") or "",
        "ステータス": status,
        "status": status,
        "ステータス理由": db_row.get("status_reason") or "",
        "status_reason": db_row.get("status_reason") or "",
        "TP0": db_row.get("tp0") or "",
        "TP1": db_row.get("tp1") or "",
        "TP2": db_row.get("tp2") or "",
        "TP3": db_row.get("tp3") or "",
        "tp0": db_row.get("tp0") or "",
        "tp1": db_row.get("tp1") or "",
        "tp2": db_row.get("tp2") or "",
        "tp3": db_row.get("tp3") or "",
        "ladder_enabled": db_row.get("ladder_enabled"),
        "ladder_rules": db_row.get("ladder_rules") or "",
        "価格改定": "OFF" if str(db_row.get("repricing_enabled", 1)).strip().lower() in ("0", "off", "false") else "ON",
        "repricing_enabled": db_row.get("repricing_enabled", 1),
    }


def pending_list_path() -> Path:
    base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "inventory_only_skus_pending.json"


def save_pending_missing_list(rows: List[Dict[str, Any]], *, csv_path: str = "") -> Path:
    path = pending_list_path()
    payload = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "csv_path": csv_path,
        "count": len(rows),
        "items": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_pending_missing_list() -> List[Dict[str, Any]]:
    path = pending_list_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items") if isinstance(data, dict) else data
        return items if isinstance(items, list) else []
    except (json.JSONDecodeError, OSError):
        return []
