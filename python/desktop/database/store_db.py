#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗マスタデータベース操作クラス

SQLiteデータベースを使用した店舗マスタ管理
- stores テーブル: 店舗基本情報 + カスタムフィールド（JSON）
- store_custom_fields テーブル: カスタムフィールド定義
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class StoreDatabase:
    """店舗マスタデータベース操作クラス"""
    
    def __init__(self, db_path: Optional[str] = None):
        """データベースの初期化"""
        if db_path is None:
            # デフォルトパス: python/desktop/data/hirio.db
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
        
        # stores テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                affiliated_route_name TEXT,
                route_code TEXT,
                supplier_code TEXT UNIQUE,
                store_name TEXT NOT NULL,
                custom_fields TEXT,  -- JSON形式
                display_order INTEGER DEFAULT 0,  -- 訪問順序（追加）
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # display_orderカラムが存在しない場合は追加（マイグレーション）
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN display_order INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            # カラムが既に存在する場合はスキップ
            pass
        
        # store_custom_fields テーブル作成（カスタムフィールド定義）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS store_custom_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_name TEXT UNIQUE NOT NULL,
                field_type TEXT NOT NULL,  -- TEXT, INTEGER, REAL, DATE
                display_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,  -- BOOLEAN (0 or 1)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # updated_atを自動更新するトリガー
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_stores_timestamp 
            AFTER UPDATE ON stores
            FOR EACH ROW
            BEGIN
                UPDATE stores SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)
        
        conn.commit()
    
    def close(self):
        """データベース接続を閉じる"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    # ==================== stores テーブル操作 ====================
    
    def add_store(self, store_data: Dict[str, Any]) -> int:
        """店舗を追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # custom_fieldsをJSON文字列に変換
        custom_fields_json = json.dumps(store_data.get('custom_fields', {}), ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO stores (
                affiliated_route_name, route_code, supplier_code, 
                store_name, custom_fields
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            store_data.get('affiliated_route_name'),
            store_data.get('route_code'),
            store_data.get('supplier_code'),
            store_data.get('store_name'),
            custom_fields_json
        ))
        
        conn.commit()
        return cursor.lastrowid
    
    def update_store(self, store_id: int, store_data: Dict[str, Any]) -> bool:
        """店舗を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # custom_fieldsをJSON文字列に変換
        custom_fields_json = json.dumps(store_data.get('custom_fields', {}), ensure_ascii=False)
        
        cursor.execute("""
            UPDATE stores SET
                affiliated_route_name = ?,
                route_code = ?,
                supplier_code = ?,
                store_name = ?,
                custom_fields = ?
            WHERE id = ?
        """, (
            store_data.get('affiliated_route_name'),
            store_data.get('route_code'),
            store_data.get('supplier_code'),
            store_data.get('store_name'),
            custom_fields_json,
            store_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_store(self, store_id: int) -> bool:
        """店舗を削除"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM stores WHERE id = ?", (store_id,))
        conn.commit()
        
        return cursor.rowcount > 0
    
    def get_store(self, store_id: int) -> Optional[Dict[str, Any]]:
        """店舗を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM stores WHERE id = ?", (store_id,))
        row = cursor.fetchone()
        
        if row:
            return self._row_to_dict(row)
        return None
    
    def get_store_by_supplier_code(self, supplier_code: str) -> Optional[Dict[str, Any]]:
        """仕入れ先コードで店舗を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM stores WHERE supplier_code = ?", (supplier_code,))
        row = cursor.fetchone()
        
        if row:
            return self._row_to_dict(row)
        return None
    
    def list_stores(self, search_term: Optional[str] = None) -> List[Dict[str, Any]]:
        """店舗一覧を取得（検索対応）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if search_term:
            search_pattern = f"%{search_term}%"
            cursor.execute("""
                SELECT * FROM stores 
                WHERE store_name LIKE ? 
                   OR supplier_code LIKE ?
                   OR affiliated_route_name LIKE ?
                   OR route_code LIKE ?
                ORDER BY store_name
            """, (search_pattern, search_pattern, search_pattern, search_pattern))
        else:
            cursor.execute("SELECT * FROM stores ORDER BY store_name")
        
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Rowを辞書に変換（custom_fieldsをパース）"""
        store_dict = dict(row)
        
        # custom_fieldsをJSONから辞書に変換
        if store_dict.get('custom_fields'):
            try:
                store_dict['custom_fields'] = json.loads(store_dict['custom_fields'])
            except json.JSONDecodeError:
                store_dict['custom_fields'] = {}
        else:
            store_dict['custom_fields'] = {}
        
        return store_dict
    
    # ==================== store_custom_fields テーブル操作 ====================
    
    def add_custom_field(self, field_data: Dict[str, Any]) -> int:
        """カスタムフィールド定義を追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO store_custom_fields (
                field_name, field_type, display_name, is_active
            ) VALUES (?, ?, ?, ?)
        """, (
            field_data.get('field_name'),
            field_data.get('field_type', 'TEXT'),
            field_data.get('display_name'),
            field_data.get('is_active', 1)
        ))
        
        conn.commit()
        return cursor.lastrowid
    
    def update_custom_field(self, field_id: int, field_data: Dict[str, Any]) -> bool:
        """カスタムフィールド定義を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE store_custom_fields SET
                field_name = ?,
                field_type = ?,
                display_name = ?,
                is_active = ?
            WHERE id = ?
        """, (
            field_data.get('field_name'),
            field_data.get('field_type'),
            field_data.get('display_name'),
            field_data.get('is_active', 1),
            field_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_custom_field(self, field_id: int) -> bool:
        """カスタムフィールド定義を削除"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM store_custom_fields WHERE id = ?", (field_id,))
        conn.commit()
        
        return cursor.rowcount > 0
    
    def get_custom_field(self, field_id: int) -> Optional[Dict[str, Any]]:
        """カスタムフィールド定義を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM store_custom_fields WHERE id = ?", (field_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def list_custom_fields(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """カスタムフィールド定義一覧を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if active_only:
            cursor.execute("SELECT * FROM store_custom_fields WHERE is_active = 1 ORDER BY display_name")
        else:
            cursor.execute("SELECT * FROM store_custom_fields ORDER BY display_name")
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ==================== ユーティリティ ====================
    
    def check_supplier_code_exists(self, supplier_code: str, exclude_id: Optional[int] = None) -> bool:
        """仕入れ先コードの重複チェック"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if exclude_id:
            cursor.execute(
                "SELECT COUNT(*) FROM stores WHERE supplier_code = ? AND id != ?",
                (supplier_code, exclude_id)
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM stores WHERE supplier_code = ?", (supplier_code,))
        
        count = cursor.fetchone()[0]
        return count > 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """統計情報を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 店舗総数
        cursor.execute("SELECT COUNT(*) FROM stores")
        total_stores = cursor.fetchone()[0]
        
        # 有効なカスタムフィールド数
        cursor.execute("SELECT COUNT(*) FROM store_custom_fields WHERE is_active = 1")
        active_fields = cursor.fetchone()[0]
        
        return {
            'total_stores': total_stores,
            'active_custom_fields': active_fields
        }
    
    def get_route_names(self) -> List[str]:
        """既存のルート名一覧を取得（重複除去、ソート済み）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT affiliated_route_name FROM stores WHERE affiliated_route_name IS NOT NULL AND affiliated_route_name != '' ORDER BY affiliated_route_name")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    
    def get_route_code_by_name(self, route_name: str) -> Optional[str]:
        """ルート名からルートコードを取得（最初に見つかったものを返す）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT route_code FROM stores WHERE affiliated_route_name = ? AND route_code IS NOT NULL AND route_code != '' LIMIT 1",
            (route_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else None
    
    def get_max_supplier_code_for_route(self, route_name: str) -> Optional[str]:
        """指定ルートの最大仕入れ先コードを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 指定ルートの仕入れ先コードをすべて取得
        cursor.execute(
            "SELECT supplier_code FROM stores WHERE affiliated_route_name = ? AND supplier_code IS NOT NULL AND supplier_code != ''",
            (route_name,)
        )
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        # 仕入れ先コードのリストを作成
        supplier_codes = [row[0] for row in rows if row[0]]
        
        if not supplier_codes:
            return None
        
        # コードを数値部分でソートするためにパース
        def parse_supplier_code(code: str) -> tuple:
            """仕入れ先コードを解析（例: 'H1-010' -> ('H1', 10)）"""
            try:
                if '-' in code:
                    prefix, number_part = code.rsplit('-', 1)
                    return (prefix, int(number_part))
                else:
                    # ハイフンがない場合は末尾が数値かチェック
                    import re
                    match = re.search(r'(\d+)$', code)
                    if match:
                        prefix = code[:match.start()]
                        number = int(match.group(1))
                        return (prefix, number)
                    return (code, 0)
            except (ValueError, AttributeError):
                return (code, 0)
        
        # 数値部分でソート
        parsed_codes = [parse_supplier_code(code) for code in supplier_codes]
        parsed_codes.sort(key=lambda x: (x[0], x[1]))
        
        # 最大値を返す
        max_prefix, max_number = parsed_codes[-1]
        
        # 元の形式に戻す（例: ('H1', 10) -> 'H1-010'）
        if max_number >= 0:
            # ゼロパディング（3桁）
            return f"{max_prefix}-{max_number:03d}"
        else:
            return f"{max_prefix}-{max_number}"
    
    def get_next_supplier_code_for_route(self, route_name: str) -> Optional[str]:
        """指定ルートの次の仕入れ先コードを生成"""
        max_code = self.get_max_supplier_code_for_route(route_name)
        
        if not max_code:
            # ルートが存在しない、または仕入れ先コードがない場合
            # ルートコードを使用して初期コードを生成
            route_code = self.get_route_code_by_name(route_name)
            if route_code:
                return f"{route_code}-001"
            return None
        
        # 最大コードから次のコードを生成
        try:
            if '-' in max_code:
                prefix, number_part = max_code.rsplit('-', 1)
                next_number = int(number_part) + 1
                # ゼロパディング（3桁）
                return f"{prefix}-{next_number:03d}"
            else:
                # ハイフンがない場合
                import re
                match = re.search(r'(\d+)$', max_code)
                if match:
                    prefix = max_code[:match.start()]
                    current_number = int(match.group(1))
                    next_number = current_number + 1
                    return f"{prefix}{next_number:03d}"
                # 数値部分が見つからない場合は'-001'を追加
                return f"{max_code}-001"
        except (ValueError, AttributeError):
            # パースできない場合は'-001'を追加
            return f"{max_code}-001"
    
    def update_store_display_order(self, route_name: str, store_orders: Dict[str, int]) -> bool:
        """ルート内の店舗の表示順序を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            for supplier_code, order in store_orders.items():
                cursor.execute("""
                    UPDATE stores 
                    SET display_order = ? 
                    WHERE affiliated_route_name = ? AND supplier_code = ?
                """, (order, route_name, supplier_code))
            conn.commit()
            return True
        except Exception as e:
            print(f"訪問順序更新エラー: {e}")
            conn.rollback()
            return False
    
    def get_stores_for_route_ordered(self, route_name: str) -> List[Dict[str, Any]]:
        """指定されたルートの店舗一覧を表示順序で取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM stores 
            WHERE affiliated_route_name = ? 
            ORDER BY display_order ASC, store_name ASC
        """, (route_name,))
        
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

