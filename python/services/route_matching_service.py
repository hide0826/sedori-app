#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート照合処理サービス（PySide6 非依存）

仕入リストとルートサマリー（店舗 IN/OUT）の照合。
FastAPI およびデスクトップアプリの双方から利用する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from desktop.services.calculation_service import CalculationService
except ImportError:
    from services.calculation_service import CalculationService


class RouteMatchingService:
    """ルート照合処理サービスクラス"""

    def __init__(self):
        self.calc_service = CalculationService()

    def match_store_code_by_time_and_profit(
        self,
        purchase_items: List[Dict[str, Any]],
        store_visits: List[Dict[str, Any]],
        time_tolerance_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        results = []

        for item in purchase_items:
            result_item = item.copy()
            matched = False
            match_confidence = 0.0
            matched_store_code = None
            match_reason = ""

            purchase_date = item.get("仕入れ日") or item.get("purchase_date")
            if isinstance(purchase_date, str):
                purchase_date = self.calc_service.parse_datetime_string(purchase_date)

            purchase_price = self._safe_float(item.get("仕入れ価格") or item.get("purchase_price", 0))
            planned_price = self._safe_float(item.get("販売予定価格") or item.get("planned_price", 0))
            estimated_profit = (
                planned_price - purchase_price if planned_price and purchase_price else None
            )

            for visit in store_visits:
                store_code = visit.get("store_code")
                if not store_code:
                    continue

                in_time = visit.get("store_in_time")
                out_time = visit.get("store_out_time")

                if isinstance(in_time, str):
                    in_time = self.calc_service.parse_datetime_string(in_time)
                if isinstance(out_time, str):
                    out_time = self.calc_service.parse_datetime_string(out_time)

                score, reason = self._calculate_match_score(
                    purchase_date,
                    purchase_price,
                    planned_price,
                    estimated_profit,
                    in_time,
                    out_time,
                    visit,
                    time_tolerance_minutes,
                )

                if score > match_confidence:
                    match_confidence = score
                    matched_store_code = store_code
                    match_reason = reason
                    matched = True

            if matched and match_confidence >= 0.5:
                result_item["matched_store_code"] = matched_store_code
                result_item["match_confidence"] = match_confidence
                result_item["match_reason"] = match_reason
                result_item["match_status"] = "auto_matched"
            else:
                candidates = self._find_candidate_stores(
                    purchase_items=[item],
                    store_visits=store_visits,
                    time_tolerance_minutes=time_tolerance_minutes,
                )
                result_item["matched_store_code"] = None
                result_item["match_confidence"] = match_confidence if matched else 0.0
                result_item["match_reason"] = match_reason if matched else "照合失敗"
                result_item["match_status"] = "manual_review_required"
                result_item["candidate_store_codes"] = [c["store_code"] for c in candidates[:3]]

            results.append(result_item)

        return results

    def _calculate_match_score(
        self,
        purchase_date: Optional[datetime],
        purchase_price: Optional[float],
        planned_price: Optional[float],
        estimated_profit: Optional[float],
        store_in_time: Optional[datetime],
        store_out_time: Optional[datetime],
        visit: Dict[str, Any],
        time_tolerance_minutes: int,
    ) -> Tuple[float, str]:
        score = 0.0
        reasons = []

        if purchase_date and store_in_time and store_out_time:
            if store_in_time <= purchase_date <= store_out_time:
                time_score = 0.5
                reasons.append("滞在時間内")
            else:
                time_score = 0.0
        else:
            time_score = 0.0

        score += time_score

        store_gross_profit = self._safe_float(visit.get("store_gross_profit"))
        if estimated_profit and store_gross_profit:
            if store_gross_profit > 0:
                profit_diff_ratio = abs(estimated_profit - store_gross_profit) / store_gross_profit
                if profit_diff_ratio <= 0.1:
                    profit_score = 0.3
                    reasons.append("粗利一致（誤差10%以内）")
                elif profit_diff_ratio <= 0.3:
                    profit_score = 0.15
                    reasons.append(f"粗利近接（誤差{profit_diff_ratio * 100:.1f}%）")
                else:
                    profit_score = 0.0
            else:
                profit_score = 0.0
        else:
            profit_score = 0.0

        score += profit_score

        if visit.get("purchase_success", False):
            success_score = 0.2
            reasons.append("仕入れ成功")
        else:
            success_score = 0.0

        score += success_score

        reason_text = "; ".join(reasons) if reasons else "照合条件不足"
        return score, reason_text

    def _find_candidate_stores(
        self,
        purchase_items: List[Dict[str, Any]],
        store_visits: List[Dict[str, Any]],
        time_tolerance_minutes: int,
    ) -> List[Dict[str, Any]]:
        candidates = []

        for visit in store_visits:
            store_code = visit.get("store_code")
            if not store_code:
                continue

            score = 0.0
            if visit.get("purchase_success", False):
                score += 0.5

            store_rating = visit.get("store_rating")
            if store_rating:
                score += store_rating * 0.1

            candidates.append({"store_code": store_code, "score": score, "visit": visit})

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", "").strip()
            return float(value)
        except (ValueError, TypeError):
            return None

    def update_purchase_items_with_store_codes(
        self,
        purchase_dataframe,
        matched_results: List[Dict[str, Any]],
        store_code_column: str = "店舗コード",
    ):
        if store_code_column not in purchase_dataframe.columns:
            purchase_dataframe[store_code_column] = ""

        for result in matched_results:
            matched_store_code = result.get("matched_store_code")
            if matched_store_code:
                idx = matched_results.index(result)
                if idx < len(purchase_dataframe):
                    purchase_dataframe.at[purchase_dataframe.index[idx], store_code_column] = (
                        matched_store_code
                    )
