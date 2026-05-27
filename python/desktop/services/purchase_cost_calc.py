#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入DBの手数料・出荷費用・費用合計・損益分岐点・見込み利益の共通計算。

- プラットフォーム手数料 + 出荷費用 が入っていればその合計を費用合計に同期
- 未入力時は 販売予定−仕入−見込み利益 から費用合計を補完（akaji/損益分岐点は使わない。改定でストップ価格に変わるため）
- 損益分岐点列は価格改定用 akaji を保持可能。経済的な損益分岐の再計算には費用合計を使用
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple, Union

import pandas as pd

COL_PLATFORM_FEE = "プラットフォーム手数料"
COL_SHIPPING = "出荷費用"
COL_TOTAL_COST = "費用合計"
COL_LEGACY_AMAZON_FEE = "Amazon手数料"

_PLATFORM_FEE_KEYS = (
    COL_PLATFORM_FEE,
    COL_LEGACY_AMAZON_FEE,
    "amazon-fee",
    "amazon_fee",
    "platform_fee",
)
_SHIPPING_KEYS = (COL_SHIPPING, "shipping_cost", "shipping-price", "shipping_price", "送料")
_TOTAL_COST_KEYS = (COL_TOTAL_COST, "total_cost", "sale_deduction")
_PURCHASE_KEYS = ("仕入れ価格", "仕入価格", "purchase_price", "cost")
_PLANNED_KEYS = ("販売予定価格", "planned_price", "price")
_PROFIT_KEYS = ("見込み利益", "expected_profit", "profit")
_BREAK_EVEN_KEYS = ("損益分岐点", "akaji", "breakEven", "break_even")

FEE_AMOUNT_COLUMNS = (COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST)


def to_float(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    if isinstance(v, float) and pd.isna(v):
        return default
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def is_fee_amount_column(name: str) -> bool:
    return name in FEE_AMOUNT_COLUMNS


def fee_components_are_unset(platform_fee: float, shipping_cost: float) -> bool:
    """手数料・出荷がともに未入力(0)なら費用合計は見込み利益から逆算する。"""
    return max(0.0, float(platform_fee or 0)) + max(0.0, float(shipping_cost or 0)) <= 0


def fee_storage_value(amount: Any) -> Any:
    """保存・レコード用: 0 円は空欄扱い。"""
    if amount is None or amount == "":
        return ""
    try:
        n = int(round(to_float(amount)))
    except (ValueError, TypeError):
        return amount
    return "" if n == 0 else n


def format_money_display(value: Any, *, zero_as_empty: bool = False) -> str:
    """テーブル表示用。zero_as_empty 時は 0 を空文字。"""
    if value is None or value == "":
        return ""
    try:
        n = int(round(to_float(value)))
    except (ValueError, TypeError):
        s = str(value).strip()
        return "" if zero_as_empty and s in ("0", "0.0") else s
    if zero_as_empty and n == 0:
        return ""
    return f"{n:,}"


def blank_zero_fee_columns_in_record(record: Dict[str, Any]) -> Dict[str, Any]:
    for col in FEE_AMOUNT_COLUMNS:
        if col in record:
            record[col] = fee_storage_value(record.get(col))
    return record


def cell_has_numeric_value(value: Any) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip() != ""


def _first_float(data: Mapping[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for key in keys:
        if key in data and cell_has_numeric_value(data.get(key)):
            return to_float(data.get(key))
    return None


def migrate_record_keys(record: Dict[str, Any]) -> Dict[str, Any]:
    """Amazon手数料 → プラットフォーム手数料（旧キーは残してもよいが新キーを優先）。"""
    if COL_PLATFORM_FEE not in record or not cell_has_numeric_value(record.get(COL_PLATFORM_FEE)):
        legacy = record.get(COL_LEGACY_AMAZON_FEE)
        if cell_has_numeric_value(legacy):
            record[COL_PLATFORM_FEE] = legacy
    return record


def read_fee_fields(data: Mapping[str, Any]) -> Tuple[float, float, float]:
    """(プラットフォーム手数料, 出荷費用, 費用合計) を読み取る。"""
    if isinstance(data, dict):
        migrate_record_keys(data)
    platform = _first_float(data, _PLATFORM_FEE_KEYS) or 0.0
    shipping = _first_float(data, _SHIPPING_KEYS) or 0.0
    total = _first_float(data, _TOTAL_COST_KEYS)
    if total is None:
        total = 0.0
    return max(0.0, platform), max(0.0, shipping), max(0.0, total)


def effective_sale_deduction(
    platform_fee: float,
    shipping_cost: float,
    total_cost: float = 0.0,
) -> float:
    """
    損益分岐点計算に使う控除額（手数料+出荷の合算イメージ）。
    内訳の合計があれば優先。なければ費用合計。どちらも無ければ 0。
    """
    component = max(0.0, float(platform_fee or 0)) + max(0.0, float(shipping_cost or 0))
    if component > 0:
        return component
    return max(0.0, float(total_cost or 0))


def compute_break_even_from_fees(
    purchase_price: float,
    platform_fee: float = 0.0,
    shipping_cost: float = 0.0,
    total_cost: float = 0.0,
) -> float:
    purchase_price = max(0.0, float(purchase_price or 0))
    deduction = effective_sale_deduction(platform_fee, shipping_cost, total_cost)
    return purchase_price + deduction


def infer_total_cost(
    purchase_price: float,
    planned_price: float,
    expected_profit: Optional[float],
    platform_fee: float,
    shipping_cost: float,
) -> Optional[float]:
    """
    費用合計の補完値。
    優先: 手数料+出荷 > 販売予定−仕入−見込み利益
    （損益分岐点/akaji は価格改定ストップ用のため逆算に使わない）
    """
    component = max(0.0, platform_fee) + max(0.0, shipping_cost)
    if component > 0:
        return round(component)

    purchase_price = max(0.0, float(purchase_price or 0))
    if (
        planned_price > 0
        and purchase_price >= 0
        and expected_profit is not None
        and cell_has_numeric_value(expected_profit)
    ):
        implied = planned_price - purchase_price - float(expected_profit)
        if implied >= -0.5:
            rounded = max(0, round(implied))
            return rounded
    return None


def sync_total_cost_field(record: Dict[str, Any]) -> Dict[str, Any]:
    """レコードの費用合計を補完・内訳から同期する。"""
    migrate_record_keys(record)
    platform, shipping, total = read_fee_fields(record)
    purchase = _first_float(record, _PURCHASE_KEYS) or 0.0
    planned = _first_float(record, _PLANNED_KEYS) or 0.0
    profit_raw = _first_float(record, _PROFIT_KEYS)

    component = platform + shipping
    if component > 0:
        record[COL_TOTAL_COST] = int(round(component))
        return record

    inferred = infer_total_cost(
        purchase,
        planned,
        profit_raw,
        platform,
        shipping,
    )
    if inferred is not None:
        record[COL_TOTAL_COST] = fee_storage_value(inferred)
    else:
        record[COL_TOTAL_COST] = ""
    blank_zero_fee_columns_in_record(record)
    return record


def recalculate_profit_fields(
    purchase_price: float,
    planned_price: float,
    platform_fee: float = 0.0,
    shipping_cost: float = 0.0,
    total_cost: float = 0.0,
    *,
    stored_profit: Any = None,
    stored_break_even: Any = None,
    prefer_stored_profit: bool = False,
    prefer_stored_break_even: bool = False,
) -> Dict[str, float]:
    """
    損益分岐点・見込み利益・想定利益率・ROI を返す。
    prefer_stored_* が True のとき CSV 取込値を優先し、もう一方を販売予定から補完。
    """
    purchase_price = max(0.0, float(purchase_price or 0))
    planned_price = max(0.0, float(planned_price or 0))
    platform_fee = max(0.0, float(platform_fee or 0))
    shipping_cost = max(0.0, float(shipping_cost or 0))

    component = platform_fee + shipping_cost
    if component > 0:
        total_cost = component
    else:
        profit_for_infer = None
        if cell_has_numeric_value(stored_profit):
            profit_for_infer = to_float(stored_profit)
        inferred = infer_total_cost(
            purchase_price,
            planned_price,
            profit_for_infer,
            platform_fee,
            shipping_cost,
        )
        if inferred is not None:
            total_cost = float(inferred)
        elif total_cost <= 0:
            total_cost = 0.0

    calc_be = compute_break_even_from_fees(
        purchase_price, platform_fee, shipping_cost, total_cost
    )
    calc_profit = planned_price - calc_be

    has_profit = prefer_stored_profit and cell_has_numeric_value(stored_profit)
    has_be = prefer_stored_break_even and cell_has_numeric_value(stored_break_even)

    break_even = calc_be
    expected_profit = calc_profit

    if has_profit:
        expected_profit = to_float(stored_profit)
    if has_be:
        break_even = to_float(stored_break_even)

    # 損益分岐点(akaji)は改定ストップ用。片方だけ CSV があるときは販売予定から補完
    if has_profit and not has_be:
        break_even = planned_price - expected_profit
    elif has_be and not has_profit:
        expected_profit = planned_price - break_even
    elif not has_be and not has_profit and total_cost > 0:
        break_even = purchase_price + total_cost
        expected_profit = planned_price - break_even

    margin = (expected_profit / planned_price * 100) if planned_price > 0 else 0.0
    roi = (expected_profit / purchase_price * 100) if purchase_price > 0 else 0.0

    effective_total = round(
        total_cost if total_cost > 0 else effective_sale_deduction(
            platform_fee, shipping_cost, total_cost
        )
    )
    return {
        COL_TOTAL_COST: effective_total,
        "損益分岐点": round(break_even),
        "見込み利益": round(expected_profit),
        "想定利益率": round(margin, 2),
        "想定ROI": round(roi, 2),
    }


def augment_purchase_cost_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """キー移行・費用合計補完・損益列の整合（スナップショット既存行向け）。"""
    migrate_record_keys(record)
    sync_total_cost_field(record)

    purchase = _first_float(record, _PURCHASE_KEYS) or 0.0
    planned = _first_float(record, _PLANNED_KEYS) or 0.0
    platform, shipping, total = read_fee_fields(record)

    fields = recalculate_profit_fields(
        purchase,
        planned,
        platform,
        shipping,
        total,
        stored_profit=record.get("見込み利益"),
        stored_break_even=record.get("損益分岐点"),
        prefer_stored_profit=cell_has_numeric_value(record.get("見込み利益")),
        prefer_stored_break_even=cell_has_numeric_value(record.get("損益分岐点")),
    )
    record[COL_TOTAL_COST] = fee_storage_value(fields[COL_TOTAL_COST])
    blank_zero_fee_columns_in_record(record)
    # 取込済みの見込み利益・損益分岐点は維持（費用合計だけ補完した場合）
    if not cell_has_numeric_value(record.get("見込み利益")):
        record["見込み利益"] = fields["見込み利益"]
    if not cell_has_numeric_value(record.get("損益分岐点")):
        record["損益分岐点"] = fields["損益分岐点"]
    if not cell_has_numeric_value(record.get("想定利益率")):
        record["想定利益率"] = fields["想定利益率"]
    if not cell_has_numeric_value(record.get("想定ROI")):
        record["想定ROI"] = fields["想定ROI"]
    return record


def augment_purchase_cost_records(records: list) -> list:
    for rec in records:
        if isinstance(rec, dict):
            augment_purchase_cost_record(rec)
    return records


def migrate_dataframe_fee_columns(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame の旧列名を新列名へ寄せる。"""
    if COL_LEGACY_AMAZON_FEE in df.columns:
        if COL_PLATFORM_FEE not in df.columns:
            df[COL_PLATFORM_FEE] = df[COL_LEGACY_AMAZON_FEE]
        else:
            mask = ~df[COL_PLATFORM_FEE].apply(cell_has_numeric_value)
            df.loc[mask, COL_PLATFORM_FEE] = df.loc[mask, COL_LEGACY_AMAZON_FEE]
    if COL_TOTAL_COST not in df.columns:
        df[COL_TOTAL_COST] = ""
    return df


def backfill_total_cost_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """行ごとに費用合計を補完し、手数料系の 0 は空欄にする。"""
    migrate_dataframe_fee_columns(df)
    fee_rows: Dict[str, list] = {col: [] for col in FEE_AMOUNT_COLUMNS if col in df.columns}
    for _, row in df.iterrows():
        rec = row.to_dict()
        sync_total_cost_field(rec)
        blank_zero_fee_columns_in_record(rec)
        for col in fee_rows:
            fee_rows[col].append(rec.get(col, ""))
    for col, values in fee_rows.items():
        df[col] = values
    return df
