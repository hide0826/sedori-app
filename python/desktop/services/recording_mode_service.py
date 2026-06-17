# -*- coding: utf-8 -*-
"""デモモード用の仮想DB作成・削除。"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

try:
    from utils.db_bootstrap import init_empty_hirio_db, is_valid_sqlite_db
    from utils.db_paths import (
        get_data_dir,
        get_recording_data_dir,
        get_recording_hirio_db_path,
        get_recording_inventory_route_db_path,
        get_recording_product_purchase_db_path,
    )
except ImportError:
    from desktop.utils.db_bootstrap import init_empty_hirio_db, is_valid_sqlite_db  # type: ignore
    from desktop.utils.db_paths import (  # type: ignore
        get_data_dir,
        get_recording_data_dir,
        get_recording_hirio_db_path,
        get_recording_inventory_route_db_path,
        get_recording_product_purchase_db_path,
    )

_MASTER_TABLES = frozenset(
    {
        "stores",
        "store_custom_fields",
        "routes",
        "company_master",
        "chain_store_code_mappings",
        "expense_destinations",
        "online_platforms",
        "online_stores",
        "wholesalers",
        "flea_markets",
        "flea_market_users",
        "account_titles",
        "credit_accounts",
        "condition_templates",
        "condition_template_items",
        "sqlite_sequence",
    }
)


def _production_hirio_db_path() -> Path:
    return get_data_dir() / "hirio.db"


def _close_db_conn(db: object) -> None:
    conn = getattr(db, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db.conn = None


def _clear_transactional_tables(db_path: Path) -> None:
    if not is_valid_sqlite_db(db_path):
        raise sqlite3.DatabaseError(f"invalid sqlite db: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            if table in _MASTER_TABLES:
                continue
            cur.execute(f'DELETE FROM "{table}"')
        conn.commit()
    finally:
        conn.close()


def _create_hirio_recording_db(recording_db: Path) -> None:
    """撮影用 hirio.db を作成（本番が使える場合はマスタのみコピー）。"""
    if recording_db.is_file():
        recording_db.unlink()

    prod_db = _production_hirio_db_path()
    if is_valid_sqlite_db(prod_db):
        shutil.copy2(prod_db, recording_db)
        _clear_transactional_tables(recording_db)
        return

    init_empty_hirio_db(str(recording_db))


def _create_product_purchase_db(db_path: str) -> None:
    try:
        from database.product_purchase_db import ProductPurchaseDatabase
    except ImportError:
        from desktop.database.product_purchase_db import ProductPurchaseDatabase  # type: ignore
    db = ProductPurchaseDatabase(db_path=db_path)
    _close_db_conn(db)


def _create_inventory_route_db(db_path: str) -> None:
    try:
        from database.inventory_route_snapshot_db import InventoryRouteSnapshotDatabase
    except ImportError:
        from desktop.database.inventory_route_snapshot_db import (  # type: ignore
            InventoryRouteSnapshotDatabase,
        )
    db = InventoryRouteSnapshotDatabase(db_path=db_path)
    _close_db_conn(db)


def create_recording_databases() -> None:
    """仮想DB一式を作成（マスタは本番からコピー、取引データは空）。"""
    recording_dir = get_recording_data_dir()
    recording_dir.mkdir(parents=True, exist_ok=True)

    recording_db = Path(get_recording_hirio_db_path())
    _create_hirio_recording_db(recording_db)

    for path, factory in (
        (get_recording_product_purchase_db_path(), _create_product_purchase_db),
        (get_recording_inventory_route_db_path(), _create_inventory_route_db),
    ):
        p = Path(path)
        if p.is_file():
            p.unlink()
        factory(path)


def delete_recording_databases() -> None:
    """仮想DBフォルダごと削除する。"""
    recording_dir = get_recording_data_dir()
    if recording_dir.exists():
        shutil.rmtree(recording_dir, ignore_errors=True)


def ensure_recording_databases_if_needed(enabled: bool) -> None:
    if not enabled:
        return
    recording_db = Path(get_recording_hirio_db_path())
    if not is_valid_sqlite_db(recording_db):
        if recording_db.parent.exists():
            delete_recording_databases()
        create_recording_databases()


def set_recording_mode_enabled(enabled: bool, previous: bool) -> None:
    """デモモードのON/OFFに応じて仮想DBを作成または削除する。"""
    if enabled and not previous:
        delete_recording_databases()
        create_recording_databases()
    elif not enabled and previous:
        delete_recording_databases()
