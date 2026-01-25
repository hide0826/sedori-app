#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品DBタブ用 仕入データスナップショット保存クラス
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional


def normalize_jan_in_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    レコード内のJANコードから.0を削除して正規化
    
    Args:
        record: 仕入データのレコード（辞書）
    
    Returns:
        JANコードが正規化されたレコード
    """
    # JANコードのキー名の候補（大文字小文字両方に対応）
    jan_keys = ['JAN', 'jan', 'JANコード', 'jan_code']
    
    for key in jan_keys:
        if key in record and record[key]:
            jan_value = record[key]
            jan_str = str(jan_value).strip()
            # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
            if jan_str.endswith(".0"):
                jan_str = jan_str[:-2]
            # 数字以外の文字を除去（念のため）
            jan_str = ''.join(c for c in jan_str if c.isdigit())
            record[key] = jan_str if jan_str else None
    
    return record


def normalize_jan_in_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    レコードリスト内の全JANコードから.0を削除して正規化
    
    Args:
        records: 仕入データのレコードリスト
    
    Returns:
        JANコードが正規化されたレコードリスト
    """
    return [normalize_jan_in_record(record.copy()) for record in records]


class ProductPurchaseDatabase:
    """商品DBの仕入データ保存専用DB操作クラス"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "hirio_product_purchase.db")
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
            CREATE TABLE IF NOT EXISTS product_purchase_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                data TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def save_snapshot(self, snapshot_name: str, data: List[Dict[str, Any]]) -> int:
        cur = self.conn.cursor()
        # JANコードの.0を削除してから保存
        normalized_data = normalize_jan_in_records(data)
        item_count = len(normalized_data)
        data_json = json.dumps(normalized_data, ensure_ascii=False, default=str)
        cur.execute(
            """
            INSERT INTO product_purchase_snapshots (snapshot_name, item_count, data)
            VALUES (?, ?, ?)
            """,
            (snapshot_name, item_count, data_json),
        )
        snapshot_id = cur.lastrowid

        # 古いスナップショットを削除（最新10件を保持）
        cur.execute(
            """
            DELETE FROM product_purchase_snapshots
            WHERE id NOT IN (
                SELECT id FROM product_purchase_snapshots
                ORDER BY created_at DESC
                LIMIT 10
            )
            """
        )

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
                datetime(created_at, 'localtime') AS created_at,
                datetime(updated_at, 'localtime') AS updated_at
            FROM product_purchase_snapshots
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
                item_count,
                data,
                datetime(created_at, 'localtime') AS created_at,
                datetime(updated_at, 'localtime') AS updated_at
            FROM product_purchase_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        data = json.loads(row["data"]) if row["data"] else []
        # JANコードの.0を削除してから返す
        normalized_data = normalize_jan_in_records(data)
        return {
            "id": row["id"],
            "snapshot_name": row["snapshot_name"],
            "item_count": row["item_count"],
            "data": normalized_data,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_snapshot(self, snapshot_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM product_purchase_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

