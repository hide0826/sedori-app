#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート関連の共通ユーティリティ

- フォルダパスからルートサマリーを特定
- ルートサマリーのフラグ（出品/証憑/画像）の更新

フォルダ名の想定形式:
    YYYYMMDDルート名
例:
    20260215つくばルート
    20260215_つくばルート（区切りあり）
    2026-02-15つくばルート（ハイフン日付＋名前）
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase

# ルート一覧（RouteListWidget）の再読込。main_window 初期化時に登録する。
_route_list_refresh_cb: Optional[Callable[[], None]] = None
_route_list_widget: Any = None


def set_route_list_refresh_callback(fn: Optional[Callable[[], None]]) -> None:
    """出品・証憑・画像フラグ更新後にルートサマリー一覧を即反映するためのコールバックを登録する。"""
    global _route_list_refresh_cb
    _route_list_refresh_cb = fn


def set_route_list_widget(widget: Any) -> None:
    """ルートサマリー一覧ウィジェットへの参照（行単位のチェック更新用）。"""
    global _route_list_widget
    _route_list_widget = widget


def _invoke_route_list_refresh(route_id: Optional[int] = None) -> None:
    """一覧を再読込する。route_id 指定時は該当行のチェック列だけ先に更新する。"""
    if route_id is not None and _route_list_widget is not None:
        refresh_fn = getattr(_route_list_widget, "refresh_route_flags", None)
        if callable(refresh_fn):
            try:
                if refresh_fn(int(route_id)):
                    return
            except Exception:
                pass
    if _route_list_refresh_cb is None:
        return
    try:
        _route_list_refresh_cb()
    except Exception:
        pass


def _parse_route_from_folder_name(folder_name: str) -> Optional[tuple[str, str]]:
    """
    フォルダ名から (route_date, route_name) を推定する。

    対応例:
        20260215つくばルート
        20260215_つくばルート
        20260215-つくばルート
        2026-02-15つくばルート
        2026_02_15_つくばルート
    """
    if not folder_name:
        return None

    name = folder_name.strip()

    # YYYY-MM-DD または YYYY_MM_DD + 区切り + ルート名
    m = re.match(
        r"^(\d{4})[-_]?(\d{2})[-_]?(\d{2})(?:[_\s\-]*)(.+)$",
        name,
    )
    if m:
        y, mo, d, route_name = m.groups()
        route_date = f"{y}-{mo}-{d}"
        route_name = route_name.strip()
        if route_name:
            return route_date, route_name

    # YYYYMMDD + ルート名（先頭8桁が日付）
    if len(name) >= 9:
        prefix = name[:8]
        if prefix.isdigit():
            rest = name[8:].lstrip("_- \t").strip()
            if rest:
                route_date = f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}"
                return route_date, rest

    return None


def _pick_route_for_date_and_name(
    route_db: RouteDatabase,
    store_db: StoreDatabase,
    route_date: str,
    route_name: str,
    route_code_hint: str,
) -> Optional[dict]:
    """日付＋ルート名から route_summaries の1行を特定する（同一日複数ルート対応）。"""
    rn = (route_name or "").strip()
    if not rn:
        return None

    # 1) 日付＋ルートコード（店舗マスタから名前→コード）
    route = route_db.get_route_summary_by_date_code(route_date, route_code_hint)
    if route:
        return route

    candidates = route_db.list_route_summaries(start_date=route_date, end_date=route_date)
    if not candidates:
        return None

    # 2) route_display_name が一致
    for c in candidates:
        if (c.get("route_display_name") or "").strip() == rn:
            return c

    # 3) 店舗マスタ上の表示名（route_code 経由）が一致
    for c in candidates:
        code = (c.get("route_code") or "").strip()
        if not code:
            continue
        disp = (store_db.get_route_name_by_code(code) or "").strip()
        if disp and disp == rn:
            return c

    # 4) ルートコードそのものが名前と一致（スポット等）
    for c in candidates:
        if (c.get("route_code") or "").strip() == rn:
            return c

    # 5) その日付に1件だけならそれを採用
    if len(candidates) == 1:
        return candidates[0]

    return None


def find_route_summary_from_folder(folder_path: str | Path) -> Optional[dict]:
    """
    フォルダパスから対応するルートサマリーを推定して取得する。

    上位ディレクトリに向かってフォルダ名を走査し、
    日付＋ルート名パターンのフォルダを見つけたら
    ルート日付＋ルート名から route_summaries を検索する。
    """
    path = Path(folder_path).resolve()
    route_db = RouteDatabase()
    store_db = StoreDatabase()

    for current in [path] + list(path.parents):
        folder_name = current.name
        parsed = _parse_route_from_folder_name(folder_name)
        if not parsed:
            continue

        route_date, route_name = parsed
        route_code = store_db.ensure_route_code(route_name)

        route = _pick_route_for_date_and_name(
            route_db, store_db, route_date, route_name, route_code
        )
        if route:
            return route

    return None


def _normalize_receipt_route_date(purchase_date: Any) -> Optional[str]:
    """レシートの purchase_date を route_summaries.route_date 形式 (yyyy-MM-dd) に正規化"""
    if not purchase_date:
        return None
    date_str = str(purchase_date).strip()
    if not date_str:
        return None
    if " " in date_str:
        date_str = date_str.split(" ")[0]
    if "T" in date_str:
        date_str = date_str.split("T")[0]
    date_str = date_str.replace("/", "-")
    try:
        from datetime import datetime
        return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return None


def find_route_summary_from_receipts(
    receipts: List[Dict[str, Any]],
    folder_path: str | Path | None = None,
) -> Optional[dict]:
    """
    レシート一覧の購入日（最多日）から route_summaries を推定する。
    フォルダパスがあれば先にフォルダ名マッチを試し、同一日に複数ルートがある場合の補助にも使う。
    """
    if not receipts:
        return None

    if folder_path:
        route = find_route_summary_from_folder(folder_path)
        if route:
            return route

    date_counter: Dict[str, int] = {}
    for receipt in receipts:
        normalized = _normalize_receipt_route_date(receipt.get("purchase_date"))
        if normalized:
            date_counter[normalized] = date_counter.get(normalized, 0) + 1

    if not date_counter:
        return None

    route_date = max(date_counter.items(), key=lambda item: item[1])[0]
    route_db = RouteDatabase()
    candidates = route_db.list_route_summaries(start_date=route_date, end_date=route_date)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    if folder_path:
        route = find_route_summary_from_folder(folder_path)
        if route and (route.get("route_date") or "")[:10] == route_date[:10]:
            return route

    return candidates[0]


def mark_route_evidence_completed(
    folder_path: str | Path | None = None,
    receipts: Optional[List[Dict[str, Any]]] = None,
) -> Optional[int]:
    """
    証憑管理の「確定」後にルートサマリーの証憑チェックを ON にする。
    1. レシート画像フォルダ名からルートを特定
    2. 失敗時はレシート日付（最多日）からルートサマリーを推定
    """
    route = None
    if folder_path:
        route = find_route_summary_from_folder(folder_path)
    if not route and receipts:
        route = find_route_summary_from_receipts(receipts, folder_path=folder_path)
    if not route:
        return None

    route_id = route.get("id")
    if not route_id:
        return None

    rid = int(route_id)
    RouteDatabase().set_route_flag(rid, "evidence_completed", True)
    _invoke_route_list_refresh(rid)
    return rid


def mark_route_flags_from_folder(
    folder_path: str | Path,
    listing_completed: bool = False,
    evidence_completed: bool = False,
    images_completed: bool = False,
) -> Optional[int]:
    """
    フォルダパスから対応するルートサマリーを推定し、
    指定されたフラグ（出品/証憑/画像）を ON にする。

    Returns:
        更新した route_id（見つからなかった場合は None）
    """
    route = find_route_summary_from_folder(folder_path)
    if not route:
        return None

    route_id = route.get("id")
    if not route_id:
        return None

    route_db = RouteDatabase()

    # 個別フラグを必要に応じて更新
    if listing_completed:
        route_db.set_route_flag(route_id, "listing_completed", True)
    if evidence_completed:
        route_db.set_route_flag(route_id, "evidence_completed", True)
    if images_completed:
        route_db.set_route_flag(route_id, "images_completed", True)

    _invoke_route_list_refresh(int(route_id))
    return route_id
