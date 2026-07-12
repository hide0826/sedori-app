# -*- coding: utf-8 -*-
"""database 層向けの DB パス解決（import フォールバックを1系統に集約）。"""

from __future__ import annotations

from typing import Optional


def resolve_hirio_db_path(db_path: Optional[str] = None) -> str:
    if db_path is not None:
        return db_path
    try:
        from utils.db_paths import get_hirio_db_path
    except ImportError:
        from desktop.utils.db_paths import get_hirio_db_path  # type: ignore
    return get_hirio_db_path()


def resolve_product_purchase_db_path(db_path: Optional[str] = None) -> str:
    if db_path is not None:
        return db_path
    try:
        from utils.db_paths import get_product_purchase_db_path
    except ImportError:
        from desktop.utils.db_paths import get_product_purchase_db_path  # type: ignore
    return get_product_purchase_db_path()


def resolve_inventory_route_db_path(db_path: Optional[str] = None) -> str:
    if db_path is not None:
        return db_path
    try:
        from utils.db_paths import get_inventory_route_db_path
    except ImportError:
        from desktop.utils.db_paths import get_inventory_route_db_path  # type: ignore
    return get_inventory_route_db_path()
