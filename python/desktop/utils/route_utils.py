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
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase


def _parse_route_from_folder_name(folder_name: str) -> Optional[tuple[str, str]]:
    """
    フォルダ名から (route_date, route_name) を推定する。

    期待フォーマット:
        YYYYMMDDルート名
    例:
        20260215つくばルート -> ("2026-02-15", "つくばルート")
    """
    if not folder_name or len(folder_name) < 9:
        return None

    prefix = folder_name[:8]
    if not prefix.isdigit():
        return None

    route_name = folder_name[8:].strip()
    if not route_name:
        return None

    route_date = f"{prefix[:4]}-{prefix[4:6]}-{prefix[6:8]}"
    return route_date, route_name


def find_route_summary_from_folder(folder_path: str | Path) -> Optional[dict]:
    """
    フォルダパスから対応するルートサマリーを推定して取得する。

    上位ディレクトリに向かってフォルダ名を走査し、
    「YYYYMMDDルート名」形式のフォルダを見つけたら
    ルート日付＋ルート名からルートコードを解決し、route_summaries を検索する。
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

        # ルート名からルートコードを解決（見つからなければルート名そのものをコードとして扱う）
        route_code = store_db.get_route_code_by_name(route_name) or route_name

        route = route_db.get_route_summary_by_date_code(route_date, route_code)
        if route:
            return route

    return None


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

    return route_id

