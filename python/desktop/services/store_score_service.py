#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗スコア集計サービス

route_visit_logs（訪問ログ）を店舗コードで集計し、
累計想定粗利・累計仕入点数・平均評価・店舗スコアを算出する。
（同一保存が store_visit_details と route_visit_logs の両方に書かれるため、
二重計上を避けて訪問ログのみを集計する。）
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

# スコア計算の基準値（重みは 評価:粗利:点数 = 40:30:30 で 0〜100）
SCORE_WEIGHT_RATING = 40.0   # 平均評価 (0〜5) → 0〜40点
SCORE_WEIGHT_PROFIT = 30.0  # 累計粗利の正規化 → 0〜30点
SCORE_WEIGHT_ITEMS = 30.0   # 累計仕入点数の正規化 → 0〜30点
PROFIT_BASELINE = 100000.0  # この金額で30点満点
ITEMS_BASELINE = 50.0       # この点数で30点満点


def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def compute_store_score(
    total_gross_profit: float,
    total_item_count: int,
    avg_rating: float,
    profit_baseline: float = PROFIT_BASELINE,
    items_baseline: float = ITEMS_BASELINE,
) -> float:
    """
    店舗スコアを 0〜100 で算出する。

    - 評価: (avg_rating / 5) * 40
    - 粗利: min(1, total_gross_profit / profit_baseline) * 30
    - 仕入点数: min(1, total_item_count / items_baseline) * 30
    """
    rating_pt = (avg_rating / 5.0) * SCORE_WEIGHT_RATING if avg_rating else 0.0
    profit_pt = min(1.0, total_gross_profit / profit_baseline) * SCORE_WEIGHT_PROFIT if profit_baseline else 0.0
    items_pt = min(1.0, total_item_count / items_baseline) * SCORE_WEIGHT_ITEMS if items_baseline else 0.0
    return round(rating_pt + profit_pt + items_pt, 1)


def merge_aggregates(
    from_route_db: List[Dict[str, Any]],
    from_visit_logs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    route_db の集計と route_visit_db の集計をマージする。
    同一 store_code は合算（粗利・点数は加算、訪問回数は加算、評価は加重平均）。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for row in from_route_db:
        code = (row.get("store_code") or "").strip()
        if not code:
            continue
        merged[code] = {
            "store_code": code,
            "total_gross_profit": _safe_float(row.get("total_gross_profit")),
            "total_item_count": _safe_int(row.get("total_item_count")),
            "visit_count": _safe_int(row.get("visit_count")),
            "avg_rating": _safe_float(row.get("avg_rating")),
            "rating_sum": _safe_float(row.get("avg_rating")) * _safe_int(row.get("visit_count")),
            "store_name": "",  # route_db の store_visit_details には店舗名列なし
        }
    for row in from_visit_logs:
        code = (row.get("store_code") or "").strip()
        if not code:
            continue
        vc = _safe_int(row.get("visit_count"))
        ar = _safe_float(row.get("avg_rating"))
        log_store_name = (row.get("store_name") or "").strip()
        if code not in merged:
            merged[code] = {
                "store_code": code,
                "total_gross_profit": 0.0,
                "total_item_count": 0,
                "visit_count": 0,
                "avg_rating": 0.0,
                "rating_sum": 0.0,
                "store_name": "",
            }
        merged[code]["total_gross_profit"] += _safe_float(row.get("total_gross_profit"))
        merged[code]["total_item_count"] += _safe_int(row.get("total_item_count"))
        merged[code]["visit_count"] += vc
        merged[code]["rating_sum"] += ar * vc
        if log_store_name and not merged[code]["store_name"]:
            merged[code]["store_name"] = log_store_name
    result = []
    for code, m in merged.items():
        vc = m["visit_count"]
        result.append({
            "store_code": code,
            "total_gross_profit": m["total_gross_profit"],
            "total_item_count": m["total_item_count"],
            "visit_count": vc,
            "avg_rating": (m["rating_sum"] / vc) if vc else 0.0,
            "store_name": m.get("store_name") or "",
        })
    return result


def _is_code_like_route_name(route_name: str) -> bool:
    """
    ルート名が「K2-001」「H1-010」のような店舗/ルートコード形式かどうか。
    この形式は過去のコードであり、表示用ルート名としては扱わない。
    """
    if not route_name or not route_name.strip():
        return True
    s = route_name.strip()
    # パターン: 英数字-数字（例: K2-001, H1-010, BO-08）
    if len(s) < 4:
        return False
    for i, c in enumerate(s):
        if c == "-":
            return i > 0 and i < len(s) - 1 and s[:i].replace(" ", "").isalnum() and s[i + 1 :].replace(" ", "").isdigit()
    return False


def get_merged_store_aggregates(
    route_db: Any,
    route_visit_db: Any,
    store_db: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    route_visit_db（訪問ログ）から店舗別集計を取得し、スコアを付与して返す。
    store_db を渡すと店舗名・ルート名を付与する。
    現在店舗一覧DBに登録されている店舗のみ集計対象とする（未登録は集計外）。

    注意: ルート保存時に同一訪問が store_visit_details と route_visit_logs の両方に
    保存されるため、二重計上を避けて route_visit_logs のみを集計する。
    """
    from_logs = route_visit_db.get_store_visit_aggregates()
    # 二重計上防止: store_visit_details は集計に含めない（同一保存で route_visit_logs にも書かれるため）
    from_route: List[Dict[str, Any]] = []
    merged = merge_aggregates(from_route, from_logs)
    store_name_map: Dict[str, str] = {}
    store_route_map: Dict[str, str] = {}
    valid_store_codes: set = set()  # 店舗一覧DBに存在する店舗コード（集計対象とする）
    # 訪問ログから店舗コード→ルート名を取得（店舗マスタにルート未登録でも補完するため）
    logs_route_map: Dict[str, str] = {}
    if hasattr(route_visit_db, "get_store_route_from_logs"):
        try:
            logs_route_map = route_visit_db.get_store_route_from_logs() or {}
        except Exception:
            pass
    if store_db and hasattr(store_db, "list_stores"):
        try:
            get_route_name_by_code = getattr(store_db, "get_route_name_by_code", None)

            def _put_maps(store_code_key: str, store_name_val: str, route_name_val: str, is_primary: bool = False) -> None:
                if not store_code_key:
                    return
                if is_primary:
                    valid_store_codes.add(store_code_key)  # 集計対象は店舗一覧DBの「店舗コード」列のみ
                store_name_map[store_code_key] = store_name_val
                if route_name_val:
                    store_route_map[store_code_key] = route_name_val

            for s in store_db.list_stores():
                sc = (s.get("store_code") or "").strip()
                sup = (s.get("supplier_code") or "").strip()
                name = (s.get("store_name") or s.get("name") or "").strip()
                aff = (s.get("affiliated_route_name") or "").strip()
                code = (s.get("route_code") or "").strip()
                route_name_val = aff or (get_route_name_by_code(code) if code and get_route_name_by_code else None) or code or ""

                # 店舗コード（メイン）: 集計対象に含める + 名前・ルート名マップ
                if sc:
                    _put_maps(sc, name, route_name_val, is_primary=True)
                # supplier_code は名前・ルート名の参照用のみ（集計対象には含めない）
                if sup and sup != sc:
                    _put_maps(sup, name, route_name_val, is_primary=False)
        except Exception:
            pass

    # 今現在の店舗一覧DBに保存されている店舗コードのみ集計（supplier_code や過去コードは除外）
    if valid_store_codes:
        merged = [row for row in merged if (row.get("store_code") or "").strip() in valid_store_codes]

    for row in merged:
        row["score"] = compute_store_score(
            row["total_gross_profit"],
            row["total_item_count"],
            row["avg_rating"],
        )
        # 店舗名: 店舗マスタを優先、なければ訪問ログから取得した名前
        row["store_name"] = (store_name_map.get(row["store_code"]) or row.get("store_name") or "").strip()
        # ルート名: 店舗マスタを優先、なければ訪問ログの直近訪問時のルート名で補完
        raw_route = (store_route_map.get(row["store_code"]) or logs_route_map.get(row["store_code"]) or "").strip()
        # K2-001, H1-010 のようなコード形式のルート名は表示しない（過去のルート名情報として集計に乗せない）
        row["route_name"] = "" if _is_code_like_route_name(raw_route) else raw_route
    return sorted(merged, key=lambda x: (-x["score"], -x["total_gross_profit"]))
