# -*- coding: utf-8 -*-
"""SQLite DB の検証・空スキーマ作成・破損ファイルの退避。"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def is_valid_sqlite_db(path: Path) -> bool:
    """SQLite ファイルかどうかを確認する。"""
    if not path.is_file() or path.stat().st_size < 100:
        return False
    try:
        header = path.read_bytes()[:16]
        if not header.startswith(b"SQLite format 3"):
            return False
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        finally:
            conn.close()
        return True
    except Exception:
        return False


def _close_db_conn(db: object) -> None:
    conn = getattr(db, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db.conn = None


def init_empty_hirio_db(db_path: str) -> None:
    """空の hirio.db を各DBクラスのスキーマ初期化で作成する。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.unlink()

    inits = []
    try:
        from database.store_db import StoreDatabase
        from database.product_db import ProductDatabase
        from database.purchase_db import PurchaseDatabase
        from database.ledger_db import LedgerDatabase
        from database.inventory_db import InventoryDatabase
        from database.route_visit_db import RouteVisitDatabase
        from database.warranty_db import WarrantyDatabase
        from database.condition_template_db import ConditionTemplateDatabase
        from database.route_db import RouteDatabase
    except ImportError:
        from desktop.database.store_db import StoreDatabase  # type: ignore
        from desktop.database.product_db import ProductDatabase  # type: ignore
        from desktop.database.purchase_db import PurchaseDatabase  # type: ignore
        from desktop.database.ledger_db import LedgerDatabase  # type: ignore
        from desktop.database.inventory_db import InventoryDatabase  # type: ignore
        from desktop.database.route_visit_db import RouteVisitDatabase  # type: ignore
        from desktop.database.warranty_db import WarrantyDatabase  # type: ignore
        from desktop.database.condition_template_db import ConditionTemplateDatabase  # type: ignore
        from desktop.database.route_db import RouteDatabase  # type: ignore

    for cls in (
        StoreDatabase,
        ProductDatabase,
        PurchaseDatabase,
        LedgerDatabase,
        InventoryDatabase,
        RouteVisitDatabase,
        WarrantyDatabase,
        ConditionTemplateDatabase,
        RouteDatabase,
    ):
        inits.append(cls(db_path=db_path))
    for db in inits:
        _close_db_conn(db)


def backup_invalid_db_file(path: Path) -> Path | None:
    """破損DBを退避する。リネームできない場合はコピー後に削除を試みる。"""
    if not path.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.corrupt.{stamp}.bak")
    try:
        path.rename(backup)
        return backup
    except OSError:
        shutil.copy2(path, backup)
        try:
            path.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"破損したDBファイルが他のプロセスで使用中のため修復できません: {path}\n"
                "HIRIO をすべて終了してから再起動してください。"
            ) from exc
        return backup


def ensure_hirio_db_at_path(db_path: str) -> None:
    """指定パスの hirio.db が使える状態になるよう整える（破損時は退避して再作成）。"""
    path = Path(db_path)
    if is_valid_sqlite_db(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup_invalid_db_file(path)
        print(
            f"[HIRIO] 破損したDBを退避しました: {db_path} "
            "(空のDBを新規作成します)"
        )
    init_empty_hirio_db(db_path)
