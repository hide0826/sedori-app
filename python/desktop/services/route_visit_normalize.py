#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート訪問ログの訪問順・滞在時間・移動時間を IN/OUT 時刻から再計算する。

ルートテンプレの訪問順が手入力やテンプレ変更で実際の訪問時刻とずれることがあるため、
route_visit_logs 保存時にルート単位で IN 時刻順に並べ直し、移動時間を付け直す。
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

NON_STORE_CODES = frozenset({"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"})

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)


def _parse_visit_datetime(value: Any, route_date: str) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.replace("T", " ", 1)
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text[:19] if len(text) > 19 else text, fmt)
        except ValueError:
            continue
    if route_date and ":" in text and " " not in text[:10]:
        try:
            parts = text.split(":")
            if len(parts) == 2:
                h, m = int(parts[0]), int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    return datetime.strptime(f"{route_date} {h:02d}:{m:02d}:00", "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass
    return None


def _format_visit_datetime(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _minutes_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None:
        return None
    if end < start:
        end = end + timedelta(days=1)
    minutes = (end - start).total_seconds() / 60.0
    return max(0.0, round(minutes, 1))


def _is_sortable_visit(visit: Dict[str, Any], route_date: str) -> bool:
    code = str(visit.get("store_code") or "").strip()
    if code in NON_STORE_CODES:
        return False
    in_dt = _parse_visit_datetime(visit.get("store_in_time"), route_date)
    out_dt = _parse_visit_datetime(visit.get("store_out_time"), route_date)
    return in_dt is not None and out_dt is not None


def normalize_route_visits(
    visits: List[Dict[str, Any]],
    route_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    1ルート分の訪問行を IN 時刻順に並べ替え、visit_order / 滞在 / 移動を再計算する。
    IN・OUT が揃っている行のみ時刻順。未入力行は末尾に元の visit_order 順で残す。
    """
    if not visits:
        return []

    resolved_date = (route_date or "").strip()
    if not resolved_date:
        for v in visits:
            d = str(v.get("route_date") or "").strip()
            if d:
                resolved_date = d
                break

    rows = [deepcopy(v) for v in visits]
    sortable: List[Tuple[datetime, int, Dict[str, Any]]] = []
    unsortable: List[Tuple[int, Dict[str, Any]]] = []

    for idx, row in enumerate(rows):
        code = str(row.get("store_code") or "").strip()
        if code in NON_STORE_CODES:
            unsortable.append((row.get("visit_order") if row.get("visit_order") is not None else 10000 + idx, row))
            continue
        in_dt = _parse_visit_datetime(row.get("store_in_time"), resolved_date)
        out_dt = _parse_visit_datetime(row.get("store_out_time"), resolved_date)
        if in_dt is None or out_dt is None:
            order_fallback = row.get("visit_order")
            try:
                order_key = int(order_fallback) if order_fallback is not None else 10000 + idx
            except (TypeError, ValueError):
                order_key = 10000 + idx
            unsortable.append((order_key, row))
            continue
        if out_dt < in_dt:
            out_dt = out_dt + timedelta(days=1)
        sortable.append((in_dt, idx, row))

    sortable.sort(key=lambda x: (x[0], x[1]))
    unsortable.sort(key=lambda x: (x[0],))

    ordered: List[Dict[str, Any]] = [item[2] for item in sortable] + [item[1] for item in unsortable]

    prev_out_dt: Optional[datetime] = None
    for order, row in enumerate(ordered, start=1):
        row["visit_order"] = order
        code = str(row.get("store_code") or "").strip()
        if code in NON_STORE_CODES:
            row["stay_duration"] = row.get("stay_duration") or 0
            row["travel_time_from_prev"] = row.get("travel_time_from_prev") or 0
            continue

        in_dt = _parse_visit_datetime(row.get("store_in_time"), resolved_date)
        out_dt = _parse_visit_datetime(row.get("store_out_time"), resolved_date)
        if in_dt is not None:
            row["store_in_time"] = _format_visit_datetime(in_dt)
        if out_dt is not None:
            if in_dt is not None and out_dt < in_dt:
                out_dt = out_dt + timedelta(days=1)
            row["store_out_time"] = _format_visit_datetime(out_dt)

        stay = _minutes_between(in_dt, out_dt)
        if stay is not None:
            row["stay_duration"] = stay

        if prev_out_dt is None or in_dt is None:
            row["travel_time_from_prev"] = 0.0
        else:
            travel = _minutes_between(prev_out_dt, in_dt)
            row["travel_time_from_prev"] = travel if travel is not None else 0.0

        if out_dt is not None:
            prev_out_dt = out_dt
        elif in_dt is not None:
            prev_out_dt = in_dt

    return ordered


def filter_actual_visits(
    visits: List[Dict[str, Any]],
    route_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """IN・OUT が両方ある実訪問のみ抽出（route_visit_logs と同基準）。"""
    if not visits:
        return []

    resolved_date = (route_date or "").strip()
    if not resolved_date:
        for v in visits:
            d = str(v.get("route_date") or "").strip()
            if d:
                resolved_date = d
                break

    return [deepcopy(v) for v in visits if _is_sortable_visit(v, resolved_date)]


def prepare_actual_visits_for_display(
    visits: List[Dict[str, Any]],
    route_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """実訪問のみ抽出し、IN 時刻順に visit_order / 滞在 / 移動を再計算する。"""
    actual = filter_actual_visits(visits, route_date)
    if not actual:
        return []
    return normalize_route_visits(actual, route_date)


def repair_all_route_visits_in_db(db: Any) -> int:
    """
    route_visit_logs の全ルートを走査し、訪問順・移動時間を補正して上書き保存する。
    Returns:
        補正を実行したルート（日付+コード）の件数
    """
    groups = db.list_route_visit_groups()
    repaired = 0
    for route_date, route_code, route_name in groups:
        visits = db.list_route_visits_raw(route_date, route_code)
        if not visits:
            continue
        normalized = normalize_route_visits(visits, route_date)
        db.replace_route_visits(route_date, route_code, route_name, normalized, normalize=False)
        repaired += 1
    return repaired
