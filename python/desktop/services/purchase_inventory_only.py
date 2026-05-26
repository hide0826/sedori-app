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
    """在庫CSVの1行から仕入DB登録用の最低限フィールドを抽出。"""
    row = df.iloc[row_index]
    sku_col = find_sku_column(df)
    sku = normalize_sku_from_cell(row.get(sku_col)) if sku_col else ""

    def _pick(*names: str) -> str:
        for name in names:
            for col in df.columns:
                if str(col).strip().lower() == name.lower():
                    v = row.get(col)
                    if v is not None and str(v).strip() and str(v).lower() != "nan":
                        s = normalize_sku_from_cell(v) if name == "sku" else str(v).strip()
                        if name != "sku" and s.startswith('="') and s.endswith('"'):
                            s = s[2:-1]
                        return s
        return ""

    asin = _pick("asin")
    title = _pick("title")
    price_raw = _pick("price")
    condition = _pick("condition", "コンディション")
    return {
        "sku": sku,
        "SKU": sku,
        "ASIN": asin,
        "asin": asin,
        "商品名": title,
        "title": title,
        "price": price_raw,
        "コンディション": condition,
        "condition": condition,
    }


def extract_rows_not_in_purchase_db(
    df: pd.DataFrame,
    purchase_db: Any,
) -> List[Dict[str, Any]]:
    """在庫CSVのうち仕入DBにSKUが無い行を抽出（重複SKUは1件）。"""
    if df is None or df.empty or purchase_db is None:
        return []
    sku_col = find_sku_column(df)
    if not sku_col:
        return []

    seen: Set[str] = set()
    missing: List[Dict[str, Any]] = []
    for i in range(len(df)):
        sku = normalize_sku_from_cell(df.iloc[i].get(sku_col))
        if not sku or sku in seen:
            continue
        seen.add(sku)
        try:
            if purchase_db.get_by_sku(sku):
                continue
        except Exception:
            pass
        item = row_dict_from_inventory_csv(df, i)
        item["row_index"] = i
        missing.append(item)
    return missing


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
    price_text = str(row.get("price") or "").replace(",", "").strip()
    planned = ""
    try:
        if price_text:
            planned = str(int(round(float(price_text))))
    except (TypeError, ValueError):
        planned = price_text
    payload: Dict[str, Any] = {
        "sku": sku,
        "status": PURCHASE_STATUS_INVENTORY_ONLY,
        "status_reason": PURCHASE_STATUS_REASON_INVENTORY_CSV,
        "status_set_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "repricing_enabled": 1 if enable_repricing else 0,
        "ladder_enabled": 1 if enable_ladder else 0,
        "ladder_rules": ladder_rules_json or "",
        "comment": row.get("comment") or "inventory_csv_register",
    }
    if planned:
        payload["planned_price"] = planned
    cond = str(row.get("コンディション") or row.get("condition") or "").strip()
    if cond:
        payload["condition_note"] = cond
    asin = str(row.get("ASIN") or row.get("asin") or "").strip()
    if asin:
        payload["asin"] = asin
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


def purchase_display_record_from_db_row(db_row: Dict[str, Any]) -> Dict[str, Any]:
    """仕入DB行を仕入DBタブ表示用の最小レコードに変換（スナップショットに無い行の追加用）。"""
    rec = purchase_record_from_db_row(db_row)
    rec["仕入れ日"] = db_row.get("purchase_date") or rec.get("仕入れ日") or ""
    rec["purchase_date"] = rec["仕入れ日"]
    rec["仕入数量"] = db_row.get("quantity") or 1
    rec["quantity"] = rec["仕入数量"]
    cn = db_row.get("condition_note")
    if cn:
        rec["コンディション"] = cn
        rec["condition"] = cn
    return rec


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
    return {
        "SKU": sku,
        "sku": sku,
        "ASIN": db_row.get("asin") or "",
        "商品名": db_row.get("product_name") or db_row.get("title") or "",
        "コンディション": db_row.get("condition_note") or "",
        "仕入れ価格": db_row.get("purchase_price") or 0,
        "purchase_price": db_row.get("purchase_price") or 0,
        "販売予定価格": db_row.get("planned_price") or 0,
        "見込み利益": db_row.get("expected_profit") or 0,
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
