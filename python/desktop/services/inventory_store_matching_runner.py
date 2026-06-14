#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""デスクトップ用：同一 SQLite を参照して照合する。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

_impl_path = Path(__file__).resolve().parents[2] / "services" / "inventory_store_matching.py"
_spec = importlib.util.spec_from_file_location("_hirio_inventory_store_matching", _impl_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"inventory_store_matching の実装が見つかりません: {_impl_path}")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def match_stores_from_purchase_data_local(
    purchase_data: List[Dict[str, Any]],
    route_summary_id: int,
    time_tolerance_minutes: int = 30,
) -> Dict[str, Any]:
    try:
        from utils.db_paths import get_hirio_db_path
    except ImportError:
        from desktop.utils.db_paths import get_hirio_db_path  # type: ignore

    return _mod.match_stores_from_purchase_data(
        purchase_data=purchase_data,
        route_summary_id=route_summary_id,
        time_tolerance_minutes=time_tolerance_minutes,
        db_path=get_hirio_db_path(),
    )


InventoryStoreMatchingError = _mod.InventoryStoreMatchingError

__all__ = ["match_stores_from_purchase_data_local", "InventoryStoreMatchingError"]
