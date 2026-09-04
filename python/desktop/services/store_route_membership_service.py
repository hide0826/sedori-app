#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗のルート所属（主所属 / 重複追加 / 削除 / 並べ替え）を一元管理するサービス。

RouteManagementDialog と RouteKanbanWidget の双方から利用し、
更新ルールの不一致を防ぐ。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

UNASSIGNED_COLUMN_KEY = "__unassigned__"


def parse_route_codes(store: Dict[str, Any]) -> List[str]:
    """店舗の route_code（カンマ区切り）をリストに変換する。"""
    raw = store.get("route_code") or ""
    return [code.strip() for code in str(raw).split(",") if code.strip()]


def store_code_from_store(store: Dict[str, Any]) -> str:
    return str(store.get("store_code") or store.get("supplier_code") or "").strip()


def store_in_route(
    store: Dict[str, Any],
    route_name: str,
    route_code: str,
) -> bool:
    """店舗が指定ルートに所属しているか（主所属 or route_code 含有）。"""
    name = (route_name or "").strip()
    code = (route_code or "").strip()
    if not code and not name:
        return False
    if code and code in parse_route_codes(store):
        return True
    aff = (store.get("affiliated_route_name") or "").strip()
    return bool(name and aff == name)


def is_primary_in_route(store: Dict[str, Any], route_name: str) -> bool:
    """主所属（affiliated_route_name）が指定ルートか。"""
    name = (route_name or "").strip()
    if not name:
        return False
    return (store.get("affiliated_route_name") or "").strip() == name


def is_completely_unassigned(store: Dict[str, Any]) -> bool:
    """ルート未所属（affiliated_route_name も route_code も空）。"""
    aff = (store.get("affiliated_route_name") or "").strip()
    codes = parse_route_codes(store)
    return not aff and not codes


def move_store_to_route(db, store_id: int, route_name: str, route_code: str) -> bool:
    """店舗の主所属を指定ルートに移動（route_code は単一に置換）。"""
    route_name = (route_name or "").strip()
    route_code = (route_code or "").strip()
    if not route_name or not route_code:
        return False
    return db.update_store(
        store_id,
        {
            "affiliated_route_name": route_name,
            "route_code": route_code,
        },
    )


def add_store_to_route(db, store_id: int, route_name: str, route_code: str) -> bool:
    """既存所属を維持したまま route_code を追加（重複追加）。"""
    route_name = (route_name or "").strip()
    route_code = (route_code or "").strip()
    if not route_code:
        return False

    store = db.get_store(store_id)
    if not store:
        return False

    existing_codes = parse_route_codes(store)
    if route_code not in existing_codes:
        existing_codes.append(route_code)
    new_route_code_str = ",".join(existing_codes) if existing_codes else None

    update_data: Dict[str, Any] = {"route_code": new_route_code_str}
    if not (store.get("affiliated_route_name") or "").strip():
        update_data["affiliated_route_name"] = route_name or None

    return db.update_store(store_id, update_data)


def remove_store_from_route(
    db,
    store_id: int,
    route_name: str,
    route_code: str,
) -> bool:
    """指定ルートの route_code を削除。主所属がそのルートなら affiliated_route_name もクリア。"""
    route_name = (route_name or "").strip()
    route_code = (route_code or "").strip()

    store = db.get_store(store_id)
    if not store:
        return False

    existing_codes = parse_route_codes(store)
    if route_code and route_code in existing_codes:
        new_codes = [c for c in existing_codes if c != route_code]
    elif route_name and (store.get("affiliated_route_name") or "").strip() == route_name:
        new_codes = [c for c in existing_codes if c != route_code] if route_code else existing_codes
    else:
        return False

    new_route_code_str = ",".join(new_codes) if new_codes else None
    update_data: Dict[str, Any] = {"route_code": new_route_code_str}
    if route_name and (store.get("affiliated_route_name") or "").strip() == route_name:
        update_data["affiliated_route_name"] = None

    return db.update_store(store_id, update_data)


def unassign_store_completely(db, store_id: int) -> bool:
    """ルート所属をすべて解除する。"""
    return db.update_store(
        store_id,
        {
            "affiliated_route_name": None,
            "route_code": None,
        },
    )


def reorder_route_stores(
    db,
    route_name: str,
    ordered_store_codes: Sequence[str],
) -> bool:
    """ルート内の display_order を訪問順に更新する。"""
    route_name = (route_name or "").strip()
    if not route_name:
        return False
    store_orders = {
        str(code).strip(): idx + 1
        for idx, code in enumerate(ordered_store_codes)
        if str(code).strip()
    }
    if not store_orders:
        return False
    return db.update_store_display_order(route_name, store_orders)


def apply_store_to_route_membership(
    db,
    store_id: int,
    route_name: str,
    route_code: str,
    *,
    allow_duplicate: bool,
) -> bool:
    """RouteManagementDialog と同じルールで1店舗をルートに所属させる。"""
    if allow_duplicate:
        return add_store_to_route(db, store_id, route_name, route_code)
    return move_store_to_route(db, store_id, route_name, route_code)


def detach_store_from_route_if_not_selected(
    db,
    store: Dict[str, Any],
    route_name: str,
    route_code: str,
    selected_store_ids: Sequence[int],
) -> bool:
    """編集ダイアログ保存時: 選択から外れた店舗を当該ルートから外す。"""
    store_id = store.get("id")
    if not store_id:
        return False

    existing_codes = parse_route_codes(store)
    if not existing_codes:
        return False

    if route_code not in existing_codes or store_id in selected_store_ids:
        return False

    new_codes = [code for code in existing_codes if code != route_code]
    new_route_code_str = ",".join(new_codes) if new_codes else None

    update_data: Dict[str, Any] = {"route_code": new_route_code_str}
    if (store.get("affiliated_route_name") or "").strip() == route_name:
        update_data["affiliated_route_name"] = None

    return db.update_store(store_id, update_data)


def build_kanban_columns_data(
    stores: Sequence[Dict[str, Any]],
    routes: Sequence[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    カンバン列ごとの店舗リストを構築する。

    Returns:
        column_key -> stores (display_order / store_name でソート済み)
    """
    columns: Dict[str, List[Dict[str, Any]]] = {UNASSIGNED_COLUMN_KEY: []}

    route_meta: List[Dict[str, str]] = []
    for route in routes:
        code = (route.get("route_code") or "").strip()
        name = (route.get("route_name") or "").strip()
        if not code:
            continue
        columns[code] = []
        route_meta.append({"route_code": code, "route_name": name})

    for store in stores:
        if is_completely_unassigned(store):
            columns[UNASSIGNED_COLUMN_KEY].append(store)
            continue

        for route in route_meta:
            code = route["route_code"]
            name = route["route_name"]
            if store_in_route(store, name, code):
                columns[code].append(store)

    def _sort_key(store: Dict[str, Any]) -> tuple:
        order = store.get("display_order")
        try:
            order_val = int(order) if order is not None else 999999
        except (TypeError, ValueError):
            order_val = 999999
        return (order_val, (store.get("store_name") or ""))

    for key in columns:
        columns[key].sort(key=_sort_key)

    return columns
