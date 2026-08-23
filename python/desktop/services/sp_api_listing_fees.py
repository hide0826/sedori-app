#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SP-API から出品日・プラットフォーム手数料・出荷費用を取得し、仕入レコードへ反映する。

- 出品日: Listings Items API の summaries.createdDate
  ※FBA出品チャネル（AMAZON）がある SKU のみ（在庫0=即売れ済みも含む。純粋な自己発送のみは除外）
- プラットフォーム手数料: Product Fees の ReferralFee + VariableClosingFee + PerItemFee
- 出荷費用: FBA のとき FBAFees（自己発送は Amazon から取れないので据え置き）
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from services.purchase_cost_calc import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        fee_storage_value,
        recalculate_profit_fields,
        to_float,
    )
except ImportError:
    from desktop.services.purchase_cost_calc import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        fee_storage_value,
        recalculate_profit_fields,
        to_float,
    )

_PLATFORM_FEE_TYPES = frozenset({"ReferralFee", "VariableClosingFee", "PerItemFee"})
_FBA_FEE_TYPES = frozenset({"FBAFees", "FBAPerUnitFulfillmentFee", "FBAPerOrderFulfillmentFee"})


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


def format_listed_date(raw: str) -> str:
    """ISO8601 などを仕入DB表示用の YYYY/MM/DD にする。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    if "T" in text:
        text = text.split("T", 1)[0]
    normalized = text.replace(".", "-").replace("/", "-")[:10]
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%Y/%m/%d")
    except ValueError:
        compact = "".join(ch for ch in text if ch.isdigit())[:8]
        try:
            return datetime.strptime(compact, "%Y%m%d").strftime("%Y/%m/%d")
        except ValueError:
            return ""


def parse_listing_created_date(listing_body: Dict[str, Any]) -> str:
    """Listings Items レスポンスから createdDate を取り出す（在庫チェックなし）。"""
    summaries = listing_body.get("summaries")
    if summaries is None and isinstance(listing_body.get("payload"), dict):
        summaries = listing_body["payload"].get("summaries")
    if not isinstance(summaries, list):
        return ""
    for row in summaries:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("createdDate") or row.get("created_date") or "").strip()
        formatted = format_listed_date(raw)
        if formatted:
            return formatted
    return ""


def _listing_fulfillment_rows(listing_body: Dict[str, Any]) -> list:
    avail = listing_body.get("fulfillmentAvailability")
    if avail is None and isinstance(listing_body.get("payload"), dict):
        avail = listing_body["payload"].get("fulfillmentAvailability")
    return avail if isinstance(avail, list) else []


def listing_has_sellable_quantity(listing_body: Dict[str, Any]) -> bool:
    """fulfillmentAvailability に在庫数量 1 以上があるか。"""
    for row in _listing_fulfillment_rows(listing_body):
        if not isinstance(row, dict):
            continue
        try:
            qty = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            return True
    return False


def listing_is_fba_listed(listing_body: Dict[str, Any]) -> bool:
    """FBA（AMAZON）出品チャネルが存在するか。在庫0（即売れ済み）でも True。"""
    return listing_is_amazon_fulfilled(listing_body) is True


def parse_listing_listed_date(listing_body: Dict[str, Any]) -> str:
    """
    仕入DBの「出品日」用。FBA出品がある SKU だけ createdDate を返す。

    createdDate は Amazon 上の出品登録日（FBA倉庫到着日ではない）。
    在庫0でも FBA チャネルがあれば採用（即売れ済みを拾う）。
    自己発送（DEFAULT のみ）や FBA 未設定の出品登録だけは除外。
    """
    if not listing_is_fba_listed(listing_body):
        return ""
    return parse_listing_created_date(listing_body)


def listing_is_amazon_fulfilled(listing_body: Dict[str, Any]) -> Optional[bool]:
    """出品レスポンスから FBA かどうかを推定。不明なら None。"""
    codes = []
    for row in _listing_fulfillment_rows(listing_body):
        if isinstance(row, dict):
            codes.append(str(row.get("fulfillmentChannelCode") or "").upper())
    if any("AMAZON" in c for c in codes):
        return True
    if any(c in ("DEFAULT", "MFN") for c in codes):
        return False
    return None


def _fee_amount(detail: Dict[str, Any]) -> float:
    final = detail.get("FinalFee") or detail.get("finalFee") or {}
    if isinstance(final, dict):
        return to_float(final.get("Amount") or final.get("amount"), 0.0)
    return 0.0


def parse_fees_estimate(fees_body: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], str]:
    """
    Product Fees レスポンスから (プラットフォーム手数料, FBA出荷費用, ステータス) を返す。
    失敗時は (None, None, エラーメッセージ)。

    内訳の入れ子（FBAFees 配下の FBAPerUnitFulfillmentFee 等）は二重加算しない。
    """
    payload = fees_body.get("payload") if isinstance(fees_body.get("payload"), dict) else fees_body
    result = payload.get("FeesEstimateResult") if isinstance(payload, dict) else None
    if result is None and isinstance(payload, dict):
        result = payload
    if not isinstance(result, dict):
        return None, None, "FeesEstimateResult がありません"

    status = str(result.get("Status") or "").strip()
    error = result.get("Error") or result.get("error") or {}
    if status and status.lower() not in ("success", ""):
        msg = ""
        if isinstance(error, dict):
            msg = str(error.get("Message") or error.get("message") or "").strip()
        return None, None, msg or f"Status={status}"

    estimate = result.get("FeesEstimate") or {}
    if not isinstance(estimate, dict):
        return None, None, "FeesEstimate がありません"

    details = estimate.get("FeeDetailList") or []
    if not isinstance(details, list):
        details = []
    platform = 0.0
    fba = 0.0
    for detail in details:
        if not isinstance(detail, dict):
            continue
        fee_type = str(detail.get("FeeType") or "").strip()
        amount = _fee_amount(detail)
        if fee_type in _PLATFORM_FEE_TYPES:
            platform += amount
        elif fee_type in _FBA_FEE_TYPES:
            fba += amount

    if platform <= 0 and fba <= 0:
        total = estimate.get("TotalFeesEstimate") or {}
        if isinstance(total, dict):
            platform = to_float(total.get("Amount") or total.get("amount"), 0.0)

    return int(round(platform)), int(round(fba)), "Success"


def record_is_fba(record: Dict[str, Any], listing_hint: Optional[bool] = None) -> bool:
    shipping = str(
        record.get("発送方法") or record.get("shippingMethod") or record.get("shipping_method") or ""
    ).strip().upper()
    if "FBA" in shipping or "AMAZON" in shipping:
        return True
    if "自己" in shipping or "MFN" in shipping or "FBM" in shipping:
        return False
    if listing_hint is not None:
        return bool(listing_hint)
    return True


def apply_listing_fees_to_record(
    record: Dict[str, Any],
    *,
    listed_date: str = "",
    platform_fee: Optional[int] = None,
    fba_shipping_fee: Optional[int] = None,
    is_fba: bool = True,
    update_listed_date: bool = True,
) -> Dict[str, Any]:
    """仕入レコードへ出品日・手数料を書き、利益系を再計算する。"""
    if update_listed_date and listed_date:
        record["出品日"] = listed_date
        record["listed_date"] = listed_date

    if platform_fee is not None:
        record[COL_PLATFORM_FEE] = fee_storage_value(platform_fee)
        record["amazon-fee"] = record[COL_PLATFORM_FEE]
        record["amazon_fee"] = record[COL_PLATFORM_FEE]

    if is_fba and fba_shipping_fee is not None:
        record[COL_SHIPPING] = fee_storage_value(fba_shipping_fee)
        record["shipping-price"] = record[COL_SHIPPING]
        record["shipping_cost"] = record[COL_SHIPPING]

    purchase = to_float(record.get("仕入れ価格") or record.get("purchase_price") or record.get("cost"), 0.0)
    planned = to_float(record.get("販売予定価格") or record.get("planned_price") or record.get("price"), 0.0)
    pf = to_float(record.get(COL_PLATFORM_FEE), 0.0)
    sh = to_float(record.get(COL_SHIPPING), 0.0)
    fields = recalculate_profit_fields(
        purchase,
        planned,
        pf,
        sh,
        pf + sh,
        prefer_stored_profit=False,
        prefer_stored_break_even=False,
    )
    record[COL_TOTAL_COST] = fee_storage_value(fields[COL_TOTAL_COST])
    record["見込み利益"] = fields["見込み利益"]
    record["損益分岐点"] = fields["損益分岐点"]
    record["想定利益率"] = fields["想定利益率"]
    record["想定ROI"] = fields["想定ROI"]
    record["expected_margin"] = fields["想定利益率"]
    record["expected_roi"] = fields["想定ROI"]
    return record


def fetch_listing_and_fees_for_sku(
    sku: str,
    listing_price: float,
    *,
    asin: str = "",
    is_fba: bool = True,
    client: Any = None,
) -> Dict[str, Any]:
    """
    1 SKU 分を SP-API から取得する。

    Returns:
        dict: listed_date, platform_fee, fba_shipping_fee, is_fba, errors(list[str])
    """
    if client is None:
        client = build_sp_api_client()

    errors: list[str] = []
    listed_date = ""
    listing_fba: Optional[bool] = None
    platform_fee: Optional[int] = None
    fba_shipping_fee: Optional[int] = None

    try:
        listing = client.get_listing_item(sku)
        listed_date = parse_listing_listed_date(listing)
        listing_fba = listing_is_amazon_fulfilled(listing)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"出品情報: {exc}")

    use_fba = bool(listing_fba) if listing_fba is not None else bool(is_fba)
    try:
        fees_body = client.get_fees_estimate_for_sku(
            sku, listing_price, is_amazon_fulfilled=use_fba
        )
        platform_fee, fba_shipping_fee, status = parse_fees_estimate(fees_body)
        if status != "Success":
            raise RuntimeError(status)
    except Exception as exc:  # noqa: BLE001
        if asin:
            try:
                fees_body = client.get_fees_estimate_for_asin(
                    asin, listing_price, is_amazon_fulfilled=use_fba
                )
                platform_fee, fba_shipping_fee, status = parse_fees_estimate(fees_body)
                if status != "Success":
                    raise RuntimeError(status)
            except Exception as exc2:  # noqa: BLE001
                errors.append(f"手数料: {exc2}")
        else:
            errors.append(f"手数料: {exc}")

    return {
        "listed_date": listed_date,
        "platform_fee": platform_fee,
        "fba_shipping_fee": fba_shipping_fee,
        "is_fba": use_fba,
        "errors": errors,
    }


def build_sp_api_client():
    """shared の SpApiClient を生成する。"""
    if _ensure_shared_on_path() is None:
        raise RuntimeError("D:/HIRIO/shared/sp_api_client.py が見つかりません。")
    from sp_api_client import SpApiClient  # noqa: WPS433

    return SpApiClient()
