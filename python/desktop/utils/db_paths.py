# -*- coding: utf-8 -*-
"""SQLite データベースファイルパスの一元管理。"""

from __future__ import annotations

from pathlib import Path

try:
    from utils.settings_helper import is_recording_mode
except ImportError:
    from desktop.utils.settings_helper import is_recording_mode  # type: ignore


def get_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def get_recording_data_dir() -> Path:
    return get_data_dir() / "recording"


def get_recording_hirio_db_path() -> str:
    """デモモード専用 hirio.db（フラグ状態に依存しない）。"""
    return str(get_recording_data_dir() / "hirio.db")


def get_recording_product_purchase_db_path() -> str:
    return str(get_recording_data_dir() / "hirio_product_purchase.db")


def get_recording_inventory_route_db_path() -> str:
    return str(get_recording_data_dir() / "hirio_inventory_route.db")


def _ensure_recording_databases_ready() -> None:
    recording_db = Path(get_recording_hirio_db_path())
    try:
        from utils.db_bootstrap import is_valid_sqlite_db
    except ImportError:
        from desktop.utils.db_bootstrap import is_valid_sqlite_db  # type: ignore
    if is_valid_sqlite_db(recording_db):
        return
    try:
        from services.recording_mode_service import create_recording_databases
    except ImportError:
        from desktop.services.recording_mode_service import create_recording_databases  # type: ignore
    create_recording_databases()


def get_hirio_db_path() -> str:
    if is_recording_mode():
        _ensure_recording_databases_ready()
        return get_recording_hirio_db_path()
    prod_path = str(get_data_dir() / "hirio.db")
    try:
        from utils.db_bootstrap import ensure_hirio_db_at_path
    except ImportError:
        from desktop.utils.db_bootstrap import ensure_hirio_db_at_path  # type: ignore
    ensure_hirio_db_at_path(prod_path)
    return prod_path


def get_product_purchase_db_path() -> str:
    if is_recording_mode():
        _ensure_recording_databases_ready()
        return get_recording_product_purchase_db_path()
    return str(get_data_dir() / "hirio_product_purchase.db")


def get_inventory_route_db_path() -> str:
    if is_recording_mode():
        _ensure_recording_databases_ready()
        return get_recording_inventory_route_db_path()
    return str(get_data_dir() / "hirio_inventory_route.db")
