# -*- coding: utf-8 -*-
"""ネット仕入箱を route_web 一覧へ自動登録する（サーバ側・軽量）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from route_web.registry import make_web_id, register_route, route_json_path
from route_web.schema import build_route_document, stamp_updated

ONLINE_ROOT_CANDIDATES = (
    Path(r"D:\せどり総合\ネット仕入れリスト"),
    Path(r"D:\せどり総合\ネット仕入リスト"),
)
CSV_DIR_NAME = "仕入CSV"
PRODUCT_DIR_NAME = "商品画像"
EVIDENCE_DIR_NAME = "証憑スクショ"
ONLINE_SUBDIRS = (CSV_DIR_NAME, PRODUCT_DIR_NAME, EVIDENCE_DIR_NAME)
ONLINE_ROUTE_CODE = "NET"
ONLINE_BOX_KIND = "online"


def resolve_online_root() -> Optional[Path]:
    for path in ONLINE_ROOT_CANDIDATES:
        try:
            if path.is_dir():
                return path
        except OSError:
            continue
    return None


def _looks_like_box(path: Path) -> bool:
    if not path.is_dir():
        return False
    name = path.name.strip()
    if not name or name.startswith("."):
        return False
    if (path / "route.json").is_file():
        return True
    if any((path / sub).is_dir() for sub in ONLINE_SUBDIRS):
        return True
    digits = "".join(ch for ch in name if ch.isdigit())
    return len(digits) >= 8


def _ymd_from_name(name: str) -> str:
    digits = "".join(ch for ch in name if ch.isdigit())
    if len(digits) >= 8:
        return digits[-8:]
    from datetime import date

    return date.today().strftime("%Y%m%d")


def ensure_online_box_registered(folder: Path) -> str:
    """箱に route.json を書き、index に登録して web_id を返す。"""
    folder.mkdir(parents=True, exist_ok=True)
    for sub in ONLINE_SUBDIRS:
        (folder / sub).mkdir(exist_ok=True)

    name = folder.name
    ymd = _ymd_from_name(name)
    iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    web_id = make_web_id(ymd, name)

    existing = {}
    path = route_json_path(folder)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except (OSError, json.JSONDecodeError):
            existing = {}

    doc = build_route_document(
        web_id=web_id,
        folder_path=str(folder),
        route_date=iso,
        route_code=ONLINE_ROUTE_CODE,
        route_name=name,
        stores=[],
        notes=str(existing.get("notes") or ""),
        box_kind=ONLINE_BOX_KIND,
    )
    for key in ("product_files", "no_image_products", "photo_candidates"):
        if isinstance(existing.get(key), list):
            doc[key] = existing[key]
    doc = stamp_updated(doc)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    register_route(web_id, str(folder), route_name=name, route_date=iso)
    return web_id


def sync_online_boxes_into_registry(root: Optional[Path] = None) -> List[str]:
    base = root or resolve_online_root()
    if base is None or not base.is_dir():
        return []
    registered: List[str] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if not _looks_like_box(child):
            continue
        try:
            registered.append(ensure_online_box_registered(child))
        except Exception as exc:
            print(f"[route_web] online box skip {child}: {exc}")
    return registered
