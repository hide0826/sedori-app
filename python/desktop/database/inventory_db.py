#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入データデータベース操作クラス

SQLiteデータベースを使用した仕入データ管理
- inventory_snapshots テーブル: 仕入データのスナップショット（最大10件）
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


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


class InventoryDatabase:
    """仕入データデータベース操作クラス"""
    
    def __init__(self, db_path: Optional[str] = None):
        """データベースの初期化"""
        if db_path is None:
            # デフォルトパス: python/desktop/data/hirio.db（既存のDBを使用）
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "hirio.db")
        
        self.db_path = db_path
        self.conn = None
        self._ensure_db_directory()
        self._init_database()
    
    def _ensure_db_directory(self):
        """データベースディレクトリの存在確認"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_connection(self):
        """データベース接続を取得"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row  # 辞書形式で結果を取得
        return self.conn
    
    def _init_database(self):
        """データベースとテーブルの初期化"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # inventory_snapshots テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                data TEXT NOT NULL,  -- JSON形式のデータ
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
    
    def save_inventory_data(self, snapshot_name: str, data: List[Dict[str, Any]]) -> int:
        """
        仕入データを保存
        
        Args:
            snapshot_name: スナップショット名
            data: 仕入データのリスト
        
        Returns:
            保存されたデータのID
        
        Note:
            10件を超える場合は古いデータを削除
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # JANコードの.0を削除してから保存
        normalized_data = normalize_jan_in_records(data)
        
        # データをJSON文字列に変換
        data_json = json.dumps(normalized_data, ensure_ascii=False, default=str)
        item_count = len(normalized_data)
        
        # データを挿入
        cursor.execute("""
            INSERT INTO inventory_snapshots (snapshot_name, item_count, data)
            VALUES (?, ?, ?)
        """, (snapshot_name, item_count, data_json))
        
        snapshot_id = cursor.lastrowid
        
        # 10件制限: 古いデータを削除
        cursor.execute("""
            DELETE FROM inventory_snapshots
            WHERE id NOT IN (
                SELECT id FROM inventory_snapshots
                ORDER BY created_at DESC
                LIMIT 10
            )
        """)
        
        conn.commit()
        
        return snapshot_id
    
    def get_all_snapshots(self) -> List[Dict[str, Any]]:
        """
        全スナップショットを取得（作成日時の降順）
        
        Returns:
            スナップショットのリスト
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id, 
                snapshot_name, 
                item_count, 
                created_at, 
                updated_at,
                datetime(created_at, 'localtime') AS created_at_local,
                datetime(updated_at, 'localtime') AS updated_at_local
            FROM inventory_snapshots
            ORDER BY created_at DESC
        """)
        
        rows = cursor.fetchall()
        
        return [{
            'id': row['id'],
            'snapshot_name': row['snapshot_name'],
            'item_count': row['item_count'],
            'created_at': row['created_at_local'] or row['created_at'],
            'updated_at': row['updated_at_local'] or row['updated_at']
        } for row in rows]
    
    def get_snapshot_by_id(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """
        指定IDのスナップショットを取得
        
        Args:
            snapshot_id: スナップショットID
        
        Returns:
            スナップショットデータ（存在しない場合はNone）
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id, snapshot_name, item_count, data, 
                created_at, updated_at,
                datetime(created_at, 'localtime') AS created_at_local,
                datetime(updated_at, 'localtime') AS updated_at_local
            FROM inventory_snapshots
            WHERE id = ?
        """, (snapshot_id,))
        
        row = cursor.fetchone()
        
        if row is None:
            return None
        
        # JSONデータをパース
        data = json.loads(row['data']) if row['data'] else []
        
        # JANコードの.0を削除してから返す
        normalized_data = normalize_jan_in_records(data)
        
        return {
            'id': row['id'],
            'snapshot_name': row['snapshot_name'],
            'item_count': row['item_count'],
            'data': normalized_data,
            'created_at': row['created_at_local'] or row['created_at'],
            'updated_at': row['updated_at_local'] or row['updated_at']
        }
    
    def delete_snapshot(self, snapshot_id: int) -> bool:
        """
        スナップショットを削除
        
        Args:
            snapshot_id: スナップショットID
        
        Returns:
            削除成功の場合True
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM inventory_snapshots
            WHERE id = ?
        """, (snapshot_id,))
        
        conn.commit()
        
        return cursor.rowcount > 0
    
    def search_snapshots(self, name_keyword: str = "") -> List[Dict[str, Any]]:
        """
        スナップショットを検索
        
        Args:
            name_keyword: スナップショット名の検索キーワード
        
        Returns:
            検索結果のリスト
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if name_keyword:
            cursor.execute("""
                SELECT 
                    id, snapshot_name, item_count, 
                    created_at, updated_at,
                    datetime(created_at, 'localtime') AS created_at_local,
                    datetime(updated_at, 'localtime') AS updated_at_local
                FROM inventory_snapshots
                WHERE snapshot_name LIKE ?
                ORDER BY created_at DESC
            """, (f'%{name_keyword}%',))
        else:
            cursor.execute("""
                SELECT 
                    id, snapshot_name, item_count, 
                    created_at, updated_at,
                    datetime(created_at, 'localtime') AS created_at_local,
                    datetime(updated_at, 'localtime') AS updated_at_local
                FROM inventory_snapshots
                ORDER BY created_at DESC
            """)
        
        rows = cursor.fetchall()
        
        return [{
            'id': row['id'],
            'snapshot_name': row['snapshot_name'],
            'item_count': row['item_count'],
            'created_at': row['created_at_local'] or row['created_at'],
            'updated_at': row['updated_at_local'] or row['updated_at']
        } for row in rows]
    
    def close(self):
        """データベース接続をクローズ"""
        if self.conn:
            self.conn.close()
            self.conn = None

