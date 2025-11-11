#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入データ＋ルートテンプレート統合スナップショットDB
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional


class InventoryRouteSnapshotDatabase:
    """仕入データとルートテンプレートの統合スナップショット管理"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "hirio_inventory_route.db")
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._ensure_dir()
        self._connect()
        self._init_schema()

    def _ensure_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> None:
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_route_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT NOT NULL,
                purchase_data TEXT NOT NULL,
                route_data TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def save_snapshot(
        self,
        snapshot_name: str,
        purchase_data: List[Dict[str, Any]],
        route_payload: Dict[str, Any],
    ) -> int:
        cur = self.conn.cursor()
        purchase_json = json.dumps(purchase_data, ensure_ascii=False, default=str)
        route_json = json.dumps(route_payload, ensure_ascii=False, default=str)
        cur.execute(
            """
            INSERT INTO inventory_route_snapshots (snapshot_name, purchase_data, route_data)
            VALUES (?, ?, ?)
            """,
            (snapshot_name, purchase_json, route_json),
        )
        snapshot_id = cur.lastrowid
        self.conn.commit()
        return snapshot_id

    def list_snapshots(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                id,
                snapshot_name,
                item_count,
                created_at,
                updated_at
            FROM (
                SELECT
                    id,
                    snapshot_name,
                    json_array_length(purchase_data) AS item_count,
                    datetime(created_at, 'localtime') AS created_at,
                    datetime(updated_at, 'localtime') AS updated_at
                FROM inventory_route_snapshots
            )
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                id,
                snapshot_name,
                purchase_data,
                route_data,
                datetime(created_at, 'localtime') AS created_at,
                datetime(updated_at, 'localtime') AS updated_at
            FROM inventory_route_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        purchase = json.loads(row["purchase_data"]) if row["purchase_data"] else []
        route = json.loads(row["route_data"]) if row["route_data"] else {}
        return {
            "id": row["id"],
            "snapshot_name": row["snapshot_name"],
            "purchase_data": purchase,
            "route_data": route,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_snapshot(self, snapshot_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM inventory_route_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

