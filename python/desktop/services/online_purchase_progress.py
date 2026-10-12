# -*- coding: utf-8 -*-
"""ネット仕入の出品CSV完了を、TOPの未実装タスクから見えるようにする。"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Union

from database.route_db import RouteDatabase
from utils.route_utils import (
    find_route_summary_by_display_name,
    parse_trailing_date_folder_name,
)

ONLINE_ROUTE_CODE = "NET"
CSV_DIR_NAME = "仕入CSV"


def box_has_listing_csv(box_dir: Union[str, Path]) -> bool:
    """箱の中に、出品CSV生成で保存したファイルがあるか。"""
    box = Path(box_dir)
    folders = [box / CSV_DIR_NAME, box]
    for folder in folders:
        if not folder.is_dir():
            continue
        try:
            files = list(folder.glob("*.csv"))
        except OSError:
            continue
        for path in files:
            if "出品" in path.name:
                return True
    return False


def resolve_online_box_dir(start: Union[str, Path]) -> Optional[Path]:
    """保存先フォルダから、ネット仕入の日付箱をさかのぼって探す。"""
    path = Path(start)
    if path.is_file():
        path = path.parent
    for current in [path] + list(path.parents):
        if parse_trailing_date_folder_name(current.name) is None:
            continue
        if (current / CSV_DIR_NAME).is_dir() or (current / "route.json").is_file():
            return current
    return None


def ensure_online_listing_summary(
    route_db: RouteDatabase,
    box_dir: Union[str, Path],
) -> Optional[int]:
    """
    出品CSVがあるネット仕入の箱を、ルートサマリーに1件残す。
    すでに画像登録済みの印は消さない。
    """
    box = Path(box_dir)
    parsed = parse_trailing_date_folder_name(box.name)
    if not parsed:
        return None
    route_date, display_name = parsed
    existing = find_route_summary_by_display_name(route_db, route_date, display_name)
    if existing and existing.get("id"):
        route_id = int(existing["id"])
        if not bool(existing.get("listing_completed") or 0):
            route_db.set_route_flag(route_id, "listing_completed", True)
        return route_id

    route_id = route_db.add_route_summary(
        {
            "route_date": route_date,
            "route_code": ONLINE_ROUTE_CODE,
            "route_display_name": display_name,
            "remarks": "ネット仕入",
            "listing_completed": True,
        }
    )
    return int(route_id) if route_id else None


def iter_online_box_dirs(roots: Iterable[Union[str, Path]]) -> List[Path]:
    boxes: List[Path] = []
    seen: set[str] = set()
    for raw in roots:
        root = Path(raw)
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            key = str(child.resolve()) if child.exists() else str(child)
            if key in seen:
                continue
            if parse_trailing_date_folder_name(child.name) is None:
                continue
            seen.add(key)
            boxes.append(child)
    return boxes


def sync_online_listing_flags(
    route_db: RouteDatabase,
    roots: Iterable[Union[str, Path]],
) -> int:
    """出品CSVがある箱だけ、未登録ならルートサマリーへ追加する。"""
    added = 0
    for box in iter_online_box_dirs(roots):
        if not box_has_listing_csv(box):
            continue
        if ensure_online_listing_summary(route_db, box):
            added += 1
    return added


def default_online_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        from utils.settings_helper import get_online_purchase_root
    except ImportError:
        from desktop.utils.settings_helper import get_online_purchase_root  # type: ignore
    try:
        from services.online_box import resolve_default_online_root
    except ImportError:
        from desktop.services.online_box import resolve_default_online_root  # type: ignore

    saved = (get_online_purchase_root() or "").strip()
    if saved:
        roots.append(Path(saved))
    default = resolve_default_online_root()
    if default is not None:
        roots.append(Path(default))
    return roots


def mark_online_listing_completed(
    save_folder: Union[str, Path],
    last_box: str = "",
    route_db: Optional[RouteDatabase] = None,
) -> Optional[int]:
    """ネット仕入で出品CSVを保存したあと、その箱を完了扱いにする。"""
    box = resolve_online_box_dir(save_folder)
    if box is None and last_box and Path(last_box).is_dir():
        box = Path(last_box)
    if box is None:
        return None
    db = route_db or RouteDatabase()
    return ensure_online_listing_summary(db, box)
