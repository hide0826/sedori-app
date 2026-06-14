#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入リスト・ルートテンプレ取込時に、店舗マスタ未登録の店舗を自動登録する。

- ファイル上の店舗コード・店舗名の紐付けはそのまま登録（既存店舗は変更しない）
- Google Maps から住所・電話・緯度経度を補完（APIキー設定時）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from services.google_maps_service import get_store_info_from_google
except ImportError:
    try:
        from google_maps_service import get_store_info_from_google  # type: ignore
    except ImportError:
        get_store_info_from_google = None  # type: ignore


NON_STORE_CODES = frozenset(
    {"出発時刻", "帰宅時刻", "往路高速代", "復路高速代"}
)


@dataclass
class StoreRegisterResult:
    added: int = 0
    skipped: int = 0
    google_ok: int = 0
    google_failed: int = 0
    errors: List[str] = field(default_factory=list)


def _normalize_entries(
    entries: Iterable[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    seen: Dict[str, str] = {}
    for raw_code, raw_name in entries:
        code = (raw_code or "").strip()
        if not code or code in NON_STORE_CODES:
            continue
        name = (raw_name or "").strip()
        if code not in seen or (not seen[code] and name):
            seen[code] = name
    return [(code, name or code) for code, name in seen.items()]


def resolve_route_from_template(
    store_db,
    route_data: Optional[Dict[str, Any]] = None,
    *,
    combo_route_name: str = "",
) -> tuple[str, str]:
    """
    テンプレート／UI からルート名・ルートコードを解決し routes マスタも整える。

    Returns:
        (route_code, affiliated_route_name)
    """
    route_data = route_data or {}
    route_name = (
        str(route_data.get("route_name") or "").strip()
        or str(route_data.get("route_name_display") or "").strip()
        or str(combo_route_name or "").strip()
        or str(route_data.get("route_code") or "").strip()
    )
    if not route_name:
        return "", ""

    route_code = store_db.get_route_code_by_name(route_name)
    if not route_code:
        route_code = route_name

    try:
        store_db.upsert_route(route_name, route_code)
    except Exception:
        pass

    return route_code, route_name


def ensure_stores_in_master(
    store_db,
    entries: Iterable[Tuple[str, str]],
    *,
    route_code: str = "",
    affiliated_route_name: str = "",
    fetch_google: bool = True,
) -> StoreRegisterResult:
    """
    店舗マスタに未登録の store_code を追加する。

    既に store_code が存在する場合は一切更新しない。
    """
    result = StoreRegisterResult()
    normalized = _normalize_entries(entries)
    if not normalized:
        return result

    route_code = (route_code or "").strip()
    affiliated_route_name = (affiliated_route_name or "").strip()

    for store_code, store_name in normalized:
        existing = store_db.get_store_by_code(store_code)
        if existing:
            result.skipped += 1
            continue

        store_data: Dict[str, Any] = {
            "store_code": store_code,
            "supplier_code": store_code,
            "store_name": store_name,
            "route_code": route_code or None,
            "affiliated_route_name": affiliated_route_name or None,
            "address": None,
            "phone": None,
            "latitude": None,
            "longitude": None,
        }

        google_query = store_name if store_name and store_name != store_code else store_code
        if fetch_google and get_store_info_from_google and google_query:
            try:
                info = get_store_info_from_google(google_query)
            except Exception as exc:
                info = None
                result.errors.append(f"{store_code}: Google取得エラー ({exc})")

            if info:
                if info.get("address"):
                    store_data["address"] = info["address"]
                if info.get("phone"):
                    store_data["phone"] = info["phone"]
                if info.get("latitude") is not None:
                    store_data["latitude"] = info["latitude"]
                if info.get("longitude") is not None:
                    store_data["longitude"] = info["longitude"]
                result.google_ok += 1
            else:
                result.google_failed += 1

        try:
            store_db.add_store(store_data)
            result.added += 1
        except Exception as exc:
            result.errors.append(f"{store_code}: 登録失敗 ({exc})")

    return result
