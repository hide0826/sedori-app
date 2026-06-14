#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートテンプレート読込後の時刻整合性チェック。

- 全体: 出発時刻と帰宅時刻はセットで必要
- 店舗: 到着(IN)と出発(OUT)はセットで必要
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

NON_STORE_CODES = frozenset({"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"})


def _time_filled(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in ("none", "nan", "-")


def collect_route_template_time_issues(
    route_data: Optional[Dict[str, Any]],
    store_visits: List[Dict[str, Any]],
) -> List[str]:
    """
    テンプレート読込直後の route_data と店舗訪問一覧から警告メッセージ行を集める。
    """
    issues: List[str] = []
    route_data = route_data or {}

    dep = _time_filled(route_data.get("departure_time"))
    ret = _time_filled(route_data.get("return_time"))

    if dep and not ret:
        issues.append(
            "・全体: 「出発時刻」は入力されていますが「帰宅時刻」がありません。"
            "稼働時間やルート全体の時間軸が正しく計算できません。"
        )
    elif ret and not dep:
        issues.append(
            "・全体: 「帰宅時刻」は入力されていますが「出発時刻」がありません。"
            "稼働時間やルート全体の時間軸が正しく計算できません。"
        )
    elif not dep and not ret:
        issues.append(
            "・全体: 「出発時刻」と「帰宅時刻」がともに未入力です。"
            "テンプレートの「出発時刻」「帰宅時刻」行（店舗コード列）を確認してください。"
        )

    store_issues: List[str] = []
    for idx, visit in enumerate(store_visits, start=1):
        code = str(visit.get("store_code") or "").strip()
        if not code or code in NON_STORE_CODES:
            continue
        name = str(visit.get("store_name") or "").strip()
        label = name or code or f"訪問{idx}"

        in_ok = _time_filled(visit.get("store_in_time"))
        out_ok = _time_filled(visit.get("store_out_time"))

        if in_ok and not out_ok:
            store_issues.append(f"・{label}: 到着時刻(IN)のみ入力（店舗の出発時刻 OUT が空）")
        elif out_ok and not in_ok:
            store_issues.append(f"・{label}: 出発時刻(OUT)のみ入力（到着時刻 IN が空）")
        # IN・OUT とも未入力は未訪問店舗のため警告しない

    if store_issues:
        issues.append(
            "・店舗ごとの到着時刻(IN)と出発時刻(OUT)が揃っていない店舗があります。"
            "照合処理・移動時間・ルート訪問DBの保存が正しくできません。"
        )
        max_show = 12
        issues.extend(store_issues[:max_show])
        if len(store_issues) > max_show:
            issues.append(f"・…他 {len(store_issues) - max_show} 店舗")

    return issues
