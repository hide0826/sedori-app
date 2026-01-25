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
        route_date: Optional[str] = None,
        route_code: Optional[str] = None,
    ) -> int:
        cur = self.conn.cursor()
        
        # 日付とルートが同じ場合は既存レコードを検索して上書き
        if route_date and route_code:
            # 既存のスナップショットを取得して、route_dataからroute_dateとroute_codeを抽出
            cur.execute(
                """
                SELECT id, route_data FROM inventory_route_snapshots
                ORDER BY created_at DESC
                """
            )
            existing_rows = cur.fetchall()
            for row in existing_rows:
                try:
                    existing_route_data = json.loads(row["route_data"])
                    existing_route = existing_route_data.get("route", {})
                    existing_route_date = existing_route.get("route_date", "")
                    existing_route_code = existing_route.get("route_code", "")
                    
                    # 日付とルートコードが一致する場合は上書き
                    if existing_route_date == route_date and existing_route_code == route_code:
                        existing_id = row["id"]
                        # JANコードの.0を削除してから保存
                        normalized_purchase_data = normalize_jan_in_records(purchase_data)
                        purchase_json = json.dumps(normalized_purchase_data, ensure_ascii=False, default=str)
                        route_json = json.dumps(route_payload, ensure_ascii=False, default=str)
                        cur.execute(
                            """
                            UPDATE inventory_route_snapshots
                            SET snapshot_name = ?, purchase_data = ?, route_data = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (snapshot_name, purchase_json, route_json, existing_id),
                        )
                        self.conn.commit()
                        return existing_id
                except (json.JSONDecodeError, KeyError):
                    # JSON解析エラーやキーエラーの場合はスキップ
                    continue
        
        # 新規保存の場合
        # JANコードの.0を削除してから保存
        normalized_purchase_data = normalize_jan_in_records(purchase_data)
        purchase_json = json.dumps(normalized_purchase_data, ensure_ascii=False, default=str)
        route_json = json.dumps(route_payload, ensure_ascii=False, default=str)
        cur.execute(
            """
            INSERT INTO inventory_route_snapshots (snapshot_name, purchase_data, route_data)
            VALUES (?, ?, ?)
            """,
            (snapshot_name, purchase_json, route_json),
        )
        snapshot_id = cur.lastrowid
        
        # 20件を超える場合は古いものから削除
        cur.execute(
            """
            SELECT id FROM inventory_route_snapshots
            ORDER BY created_at ASC
            """
        )
        all_ids = [row["id"] for row in cur.fetchall()]
        if len(all_ids) > 20:
            # 古いものから削除（created_atが古い順に削除）
            ids_to_delete = all_ids[:-20]  # 最新20件以外を取得
            if ids_to_delete:
                placeholders = ",".join("?" * len(ids_to_delete))
                cur.execute(
                    f"DELETE FROM inventory_route_snapshots WHERE id IN ({placeholders})",
                    ids_to_delete,
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
        # JANコードの.0を削除してから返す
        normalized_purchase = normalize_jan_in_records(purchase)
        return {
            "id": row["id"],
            "snapshot_name": row["snapshot_name"],
            "purchase_data": normalized_purchase,
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

