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
                address TEXT,
                phone TEXT,
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
        
        # google_map_urlカラムが存在しない場合は追加（マイグレーション）
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN google_map_url TEXT")
        except sqlite3.OperationalError:
            # カラムが既に存在する場合はスキップ
            pass
        
        # notesカラムが存在しない場合は追加（マイグレーション）
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN notes TEXT")
        except sqlite3.OperationalError:
            # カラムが既に存在する場合はスキップ
            pass
        # address / phone カラムが存在しない場合は追加（マイグレーション）
        for col, ddl in (
            ("address", "ALTER TABLE stores ADD COLUMN address TEXT"),
            ("phone", "ALTER TABLE stores ADD COLUMN phone TEXT"),
        ):
            try:
                cursor.execute(ddl)
            except sqlite3.OperationalError:
                pass
        # store_codeカラムが存在しない場合は追加（マイグレーション）
        # UNIQUE制約は後で追加する（既存データがある場合にエラーになるため）
        try:
            cursor.execute("ALTER TABLE stores ADD COLUMN store_code TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # カラムが既に存在する場合はスキップ
            pass
        
        # routes テーブル作成（ルート情報管理）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_name TEXT UNIQUE NOT NULL,
                route_code TEXT UNIQUE NOT NULL,
                google_map_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # updated_atを自動更新するトリガー（routes）
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_routes_timestamp 
            AFTER UPDATE ON routes
            FOR EACH ROW
            BEGIN
                UPDATE routes SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)
        
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
        
        # company_master テーブル作成（法人マスタ）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_name TEXT NOT NULL,
                company_name TEXT NOT NULL,
                license_number TEXT,
                head_office_address TEXT,
                representative_phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        
        # company_master の updated_at を自動更新するトリガー
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_company_master_timestamp 
            AFTER UPDATE ON company_master
            FOR EACH ROW
            BEGIN
                UPDATE company_master SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)
        
        # chain_store_code_mappings テーブル作成（チェーン店コードマッピング）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chain_store_code_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_code TEXT NOT NULL,
                chain_name_patterns TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                -- マッチしない店舗に付与する「その他」用フラグ（0 or 1）
                is_default_for_others INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 既存テーブルにis_default_for_othersカラムがない場合は追加（マイグレーション）
        try:
            cursor.execute(
                "ALTER TABLE chain_store_code_mappings "
                "ADD COLUMN is_default_for_others INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            # 既に存在する場合は無視
            pass
        
        # chain_store_code_mappings の updated_at を自動更新するトリガー
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_chain_store_code_mappings_timestamp 
            AFTER UPDATE ON chain_store_code_mappings
            FOR EACH ROW
            BEGIN
                UPDATE chain_store_code_mappings SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
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
                store_name, address, phone, custom_fields, store_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_data.get('affiliated_route_name'),
            store_data.get('route_code'),
            store_data.get('supplier_code'),
            store_data.get('store_name'),
            store_data.get('address'),
            store_data.get('phone'),
            custom_fields_json,
            store_data.get('store_code')
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
                address = ?,
                phone = ?,
                custom_fields = ?,
                store_code = ?
            WHERE id = ?
        """, (
            store_data.get('affiliated_route_name'),
            store_data.get('route_code'),
            store_data.get('supplier_code'),
            store_data.get('store_name'),
            store_data.get('address'),
            store_data.get('phone'),
            custom_fields_json,
            store_data.get('store_code'),
            store_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def update_store_notes(self, store_id: int, notes: str) -> bool:
        """店舗の備考のみを更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE stores SET notes = ? WHERE id = ?
        """, (notes, store_id))
        
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
        """仕入れ先コードで店舗を取得（後方互換用）

        新しいコードでは get_store_by_code() の使用を推奨。
        """
        if not supplier_code:
            return None
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM stores WHERE supplier_code = ?", (supplier_code,))
        row = cursor.fetchone()
        
        if row:
            return self._row_to_dict(row)
        return None

    def get_store_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """店舗コードまたは仕入れ先コードから店舗を取得

        - まず store_code で一致を検索
        - 見つからない場合は supplier_code で検索（旧データ互換）
        """
        if not code:
            return None
        conn = self._get_connection()
        cursor = conn.cursor()

        # 1. store_code 優先
        cursor.execute("SELECT * FROM stores WHERE store_code = ?", (code,))
        row = cursor.fetchone()
        if row:
            return self._row_to_dict(row)

        # 2. 互換性のため supplier_code も見る
        cursor.execute("SELECT * FROM stores WHERE supplier_code = ?", (code,))
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
                   OR store_code LIKE ?
                   OR affiliated_route_name LIKE ?
                   OR route_code LIKE ?
                ORDER BY store_name
            """, (search_pattern, search_pattern, search_pattern, search_pattern, search_pattern))
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
    
    def get_route_name_by_code(self, route_code: str) -> Optional[str]:
        """ルートコードからルート名を取得（routesテーブルを優先、なければstoresテーブルから）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # まずroutesテーブルから取得を試みる
        cursor.execute(
            "SELECT route_name FROM routes WHERE route_code = ? LIMIT 1",
            (route_code,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
        
        # routesテーブルにない場合はstoresテーブルから取得
        cursor.execute(
            "SELECT affiliated_route_name FROM stores WHERE route_code = ? AND affiliated_route_name IS NOT NULL AND affiliated_route_name != '' LIMIT 1",
            (route_code,)
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
    
    # ==================== routes テーブル操作 ====================
    
    def list_routes_with_store_count(self) -> List[Dict[str, Any]]:
        """ルート一覧を店舗数付きで取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # ルート名でグループ化して店舗数を集計
        cursor.execute("""
            SELECT 
                s.affiliated_route_name AS route_name,
                s.route_code AS route_code,
                COUNT(*) AS store_count
            FROM stores s
            WHERE s.affiliated_route_name IS NOT NULL 
                AND s.affiliated_route_name != ''
            GROUP BY s.affiliated_route_name, s.route_code
            ORDER BY s.route_code, s.affiliated_route_name
        """)
        
        rows = cursor.fetchall()
        routes = []
        
        for row in rows:
            route_name = row[0]
            route_code = row[1]
            store_count = row[2]
            
            # routes テーブルから Google Map URL を取得
            cursor.execute("""
                SELECT google_map_url FROM routes 
                WHERE route_name = ? OR route_code = ?
            """, (route_name, route_code))
            
            url_row = cursor.fetchone()
            google_map_url = url_row[0] if url_row else ''
            
            routes.append({
                'route_name': route_name,
                'route_code': route_code,
                'store_count': store_count,
                'google_map_url': google_map_url
            })
        
        return routes
    
    def update_route_google_map_url(self, route_name: str, google_map_url: str) -> bool:
        """ルートの Google Map URL を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # まず routes テーブルに該当ルートが存在するか確認
            cursor.execute("SELECT id FROM routes WHERE route_name = ?", (route_name,))
            existing_route = cursor.fetchone()
            
            if existing_route:
                # 既存ルートのURLを更新
                cursor.execute("""
                    UPDATE routes 
                    SET google_map_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE route_name = ?
                """, (google_map_url, route_name))
            else:
                # 新規ルートとして追加
                # route_code を取得
                cursor.execute("""
                    SELECT DISTINCT route_code 
                    FROM stores 
                    WHERE affiliated_route_name = ? 
                    LIMIT 1
                """, (route_name,))
                
                route_code_row = cursor.fetchone()
                if route_code_row:
                    route_code = route_code_row[0]
                    cursor.execute("""
                        INSERT INTO routes (route_name, route_code, google_map_url)
                        VALUES (?, ?, ?)
                    """, (route_name, route_code, google_map_url))
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"Google Map URL更新エラー: {e}")
            conn.rollback()
            return False
    
    # ==================== company_master テーブル操作 ====================
    
    def add_company(self, company_data: Dict[str, Any]) -> int:
        """法人を追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO company_master (
                chain_name, company_name, license_number, 
                head_office_address, representative_phone
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            company_data.get('chain_name'),
            company_data.get('company_name'),
            company_data.get('license_number'),
            company_data.get('head_office_address'),
            company_data.get('representative_phone')
        ))
        
        conn.commit()
        return cursor.lastrowid
    
    def update_company(self, company_id: int, company_data: Dict[str, Any]) -> bool:
        """法人を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE company_master SET
                chain_name = ?,
                company_name = ?,
                license_number = ?,
                head_office_address = ?,
                representative_phone = ?
            WHERE id = ?
        """, (
            company_data.get('chain_name'),
            company_data.get('company_name'),
            company_data.get('license_number'),
            company_data.get('head_office_address'),
            company_data.get('representative_phone'),
            company_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_company(self, company_id: int) -> bool:
        """法人を削除"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM company_master WHERE id = ?", (company_id,))
        conn.commit()
        
        return cursor.rowcount > 0
    
    def get_company(self, company_id: int) -> Optional[Dict[str, Any]]:
        """法人を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM company_master WHERE id = ?", (company_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def list_companies(self, search_term: Optional[str] = None) -> List[Dict[str, Any]]:
        """法人一覧を取得（検索対応）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if search_term:
            search_pattern = f"%{search_term}%"
            cursor.execute("""
                SELECT * FROM company_master 
                WHERE chain_name LIKE ? 
                   OR company_name LIKE ?
                   OR license_number LIKE ?
                ORDER BY chain_name, company_name
            """, (search_pattern, search_pattern, search_pattern))
        else:
            cursor.execute("SELECT * FROM company_master ORDER BY chain_name, company_name")
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def get_company_count(self) -> int:
        """法人数を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM company_master")
        return cursor.fetchone()[0]
    
    # ==================== chain_store_code_mappings テーブル操作 ====================
    
    def add_chain_store_code_mapping(self, mapping_data: Dict[str, Any]) -> int:
        """チェーン店コードマッピングを追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # chain_name_patternsをJSON文字列に変換
        patterns_json = json.dumps(mapping_data.get('chain_name_patterns', []), ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO chain_store_code_mappings (
                chain_code, chain_name_patterns, is_active, priority, is_default_for_others
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            mapping_data.get('chain_code'),
            patterns_json,
            mapping_data.get('is_active', 1),
            mapping_data.get('priority', 0),
            mapping_data.get('is_default_for_others', 0),
        ))
        
        conn.commit()
        return cursor.lastrowid
    
    def update_chain_store_code_mapping(self, mapping_id: int, mapping_data: Dict[str, Any]) -> bool:
        """チェーン店コードマッピングを更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        patterns_json = json.dumps(mapping_data.get('chain_name_patterns', []), ensure_ascii=False)
        
        cursor.execute("""
            UPDATE chain_store_code_mappings SET
                chain_code = ?,
                chain_name_patterns = ?,
                is_active = ?,
                priority = ?,
                is_default_for_others = ?
            WHERE id = ?
        """, (
            mapping_data.get('chain_code'),
            patterns_json,
            mapping_data.get('is_active', 1),
            mapping_data.get('priority', 0),
            mapping_data.get('is_default_for_others', 0),
            mapping_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_chain_store_code_mapping(self, mapping_id: int) -> bool:
        """チェーン店コードマッピングを削除"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM chain_store_code_mappings WHERE id = ?", (mapping_id,))
        conn.commit()
        
        return cursor.rowcount > 0
    
    def get_chain_store_code_mapping(self, mapping_id: int) -> Optional[Dict[str, Any]]:
        """チェーン店コードマッピングを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM chain_store_code_mappings WHERE id = ?", (mapping_id,))
        row = cursor.fetchone()
        
        if row:
            return self._chain_mapping_row_to_dict(row)
        return None
    
    def list_chain_store_code_mappings(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """チェーン店コードマッピング一覧を取得（優先度順）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if active_only:
            cursor.execute("""
                SELECT * FROM chain_store_code_mappings 
                WHERE is_active = 1 
                ORDER BY priority DESC, chain_code ASC
            """)
        else:
            cursor.execute("""
                SELECT * FROM chain_store_code_mappings 
                ORDER BY priority DESC, chain_code ASC
            """)
        
        rows = cursor.fetchall()
        return [self._chain_mapping_row_to_dict(row) for row in rows]
    
    def _chain_mapping_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Rowを辞書に変換（chain_name_patternsをパース）"""
        mapping_dict = dict(row)
        
        # chain_name_patternsをJSONからリストに変換
        if mapping_dict.get('chain_name_patterns'):
            try:
                mapping_dict['chain_name_patterns'] = json.loads(mapping_dict['chain_name_patterns'])
            except json.JSONDecodeError:
                mapping_dict['chain_name_patterns'] = []
        else:
            mapping_dict['chain_name_patterns'] = []

        # is_default_for_others が存在しない旧レコードの場合に備えてデフォルト値を設定
        if 'is_default_for_others' not in mapping_dict or mapping_dict['is_default_for_others'] is None:
            mapping_dict['is_default_for_others'] = 0
        
        return mapping_dict
    
    def find_chain_code_by_store_name(self, store_name: str) -> Optional[str]:
        """店舗名からチェーン店コードを検索"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 優先度順に取得
        cursor.execute("""
            SELECT chain_code, chain_name_patterns 
            FROM chain_store_code_mappings 
            WHERE is_active = 1 
            ORDER BY priority DESC, chain_code ASC
        """)
        
        rows = cursor.fetchall()
        
        for row in rows:
            chain_code = row[0]
            patterns_json = row[1]
            
            try:
                patterns = json.loads(patterns_json)
                # 店舗名にパターンが含まれているかチェック（大文字小文字を区別しない）
                store_name_upper = store_name.upper()
                for pattern in patterns:
                    if pattern.upper() in store_name_upper:
                        return chain_code
            except json.JSONDecodeError:
                continue

        # どのパターンにもマッチしなかった場合は「その他」用のチェーンコードがあればそれを返す
        try:
            cursor.execute(
                """
                SELECT chain_code FROM chain_store_code_mappings
                WHERE is_active = 1 AND is_default_for_others = 1
                ORDER BY priority DESC, chain_code ASC
                LIMIT 1
                """
            )
            default_row = cursor.fetchone()
            if default_row:
                return default_row[0]
        except Exception:
            # ここでのエラーは致命的ではないので黙ってフォールバックさせる
            pass

        return None
    
    def get_max_supplier_code_for_prefix(self, prefix: str) -> Optional[str]:
        """指定プレフィックスの最大仕入れ先コードを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT supplier_code FROM stores WHERE supplier_code LIKE ? AND supplier_code IS NOT NULL AND supplier_code != ''",
            (f"{prefix}-%",)
        )
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        supplier_codes = [row[0] for row in rows if row[0]]
        
        if not supplier_codes:
            return None
        
        # コードを数値部分でソート
        def parse_supplier_code(code: str) -> tuple:
            """仕入れ先コードを解析（例: 'BO-01' -> ('BO', 1)）"""
            try:
                if '-' in code:
                    code_prefix, number_part = code.rsplit('-', 1)
                    if code_prefix == prefix:  # プレフィックスが一致する場合のみ
                        return (code_prefix, int(number_part))
            except (ValueError, AttributeError):
                pass
            return (prefix, 0)
        
        parsed_codes = [parse_supplier_code(code) for code in supplier_codes]
        parsed_codes = [pc for pc in parsed_codes if pc[0] == prefix]  # プレフィックス一致のみ
        if not parsed_codes:
            return None
        
        parsed_codes.sort(key=lambda x: x[1])
        max_prefix, max_number = parsed_codes[-1]
        
        return f"{max_prefix}-{max_number:02d}"
    
    def _extract_store_prefix(self, store_name: str) -> str:
        """店舗名からプレフィックスを抽出（フォールバック用）"""
        import re
        alpha_only = re.sub(r'[^A-Za-z]', '', store_name)
        
        if not alpha_only:
            if len(store_name) >= 2:
                prefix = store_name[:2].upper()
                if not re.match(r'^[A-Z0-9]+$', prefix):
                    prefix = 'ST'
                return prefix[:2]
            return 'ST'
        
        return alpha_only[:2].upper()
    
    def get_next_supplier_code_from_store_name(self, store_name: str) -> str:
        """店舗名から次の仕入れ先コードを生成"""
        # チェーン店コードマッピングから検索
        chain_code = self.find_chain_code_by_store_name(store_name)
        
        if not chain_code:
            # マッピングが見つからない場合は、店舗名から自動抽出
            chain_code = self._extract_store_prefix(store_name)
        
        # 既存の最大コードを取得
        max_code = self.get_max_supplier_code_for_prefix(chain_code)
        
        if not max_code:
            return f"{chain_code}-01"
        
        try:
            if '-' in max_code:
                code_prefix, number_part = max_code.rsplit('-', 1)
                if code_prefix == chain_code:
                    next_number = int(number_part) + 1
                    return f"{code_prefix}-{next_number:02d}"
            return f"{chain_code}-01"
        except (ValueError, AttributeError):
            return f"{chain_code}-01"
    
    # ==================== store_code 関連メソッド ====================
    
    def get_max_store_code_for_prefix(self, prefix: str) -> Optional[str]:
        """指定プレフィックスの最大店舗コードを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # store_codeカラムが存在するか確認し、なければ追加
        try:
            cursor.execute("SELECT store_code FROM stores LIMIT 1")
        except sqlite3.OperationalError:
            # カラムが存在しない場合は追加（UNIQUE制約なし）
            try:
                cursor.execute("ALTER TABLE stores ADD COLUMN store_code TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                # 既に追加されている場合やその他のエラーは無視
                pass
        
        cursor.execute(
            "SELECT store_code FROM stores WHERE store_code LIKE ? AND store_code IS NOT NULL AND store_code != ''",
            (f"{prefix}-%",)
        )
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        store_codes = [row[0] for row in rows if row[0]]
        
        if not store_codes:
            return None
        
        # コードを数値部分でソート
        def parse_store_code(code: str) -> tuple:
            """店舗コードを解析（例: 'BO-01' -> ('BO', 1)）"""
            try:
                if '-' in code:
                    code_prefix, number_part = code.rsplit('-', 1)
                    if code_prefix == prefix:  # プレフィックスが一致する場合のみ
                        return (code_prefix, int(number_part))
            except (ValueError, AttributeError):
                pass
            return (prefix, 0)
        
        parsed_codes = [parse_store_code(code) for code in store_codes]
        parsed_codes = [pc for pc in parsed_codes if pc[0] == prefix]  # プレフィックス一致のみ
        if not parsed_codes:
            return None
        
        parsed_codes.sort(key=lambda x: x[1])
        max_prefix, max_number = parsed_codes[-1]
        
        return f"{max_prefix}-{max_number:02d}"
    
    def get_next_store_code_from_store_name(self, store_name: str) -> str:
        """店舗名から次の店舗コードを生成"""
        # チェーン店コードマッピングから検索
        chain_code = self.find_chain_code_by_store_name(store_name)
        
        if not chain_code:
            # マッピングが見つからない場合は、その他用のデフォルトコードを検索
            chain_code = self.find_default_chain_code_for_others()
            if not chain_code:
                # その他用も見つからない場合は、店舗名から自動抽出
                chain_code = self._extract_store_prefix(store_name)
        
        # 既存の最大コードを取得
        max_code = self.get_max_store_code_for_prefix(chain_code)
        
        if not max_code:
            return f"{chain_code}-01"
        
        try:
            if '-' in max_code:
                code_prefix, number_part = max_code.rsplit('-', 1)
                if code_prefix == chain_code:
                    next_number = int(number_part) + 1
                    return f"{code_prefix}-{next_number:02d}"
            return f"{chain_code}-01"
        except (ValueError, AttributeError):
            return f"{chain_code}-01"
    
    def find_default_chain_code_for_others(self) -> Optional[str]:
        """その他用のデフォルトチェーンコードを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # is_default_for_others = 1 かつ is_active = 1 のチェーンコードを取得
        cursor.execute("""
            SELECT chain_code 
            FROM chain_store_code_mappings 
            WHERE is_default_for_others = 1 AND is_active = 1 
            ORDER BY priority DESC, chain_code ASC
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        return row[0] if row else None
    
    def update_store_code(self, store_id: int, store_code: str) -> bool:
        """店舗コードを更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # store_codeカラムが存在するか確認し、なければ追加
        try:
            cursor.execute("SELECT store_code FROM stores LIMIT 1")
        except sqlite3.OperationalError:
            # カラムが存在しない場合は追加（UNIQUE制約なし）
            try:
                cursor.execute("ALTER TABLE stores ADD COLUMN store_code TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                # 既に追加されている場合やその他のエラーは無視
                pass
        
        cursor.execute("""
            UPDATE stores SET store_code = ? WHERE id = ?
        """, (store_code, store_id))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def assign_store_codes_to_empty_stores(self) -> Dict[str, int]:
        """店舗コードが空の店舗に自動付与"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # store_codeカラムが存在するか確認し、なければ追加
        try:
            cursor.execute("SELECT store_code FROM stores LIMIT 1")
        except sqlite3.OperationalError as e:
            # カラムが存在しない場合は追加（UNIQUE制約なし）
            try:
                cursor.execute("ALTER TABLE stores ADD COLUMN store_code TEXT")
                conn.commit()
                # カラム追加後、再度確認
                cursor.execute("SELECT store_code FROM stores LIMIT 1")
            except sqlite3.OperationalError as e2:
                # カラム追加に失敗した場合はエラーを再発生
                raise Exception(f"store_codeカラムの追加に失敗しました: {str(e2)}")
        
        # 店舗コードが空の店舗を取得
        try:
            cursor.execute("""
                SELECT id, store_name FROM stores 
                WHERE (store_code IS NULL OR store_code = '')
                ORDER BY id
            """)
        except sqlite3.OperationalError as e:
            raise Exception(f"店舗データの取得に失敗しました: {str(e)}")
        
        rows = cursor.fetchall()
        updated_count = 0
        error_count = 0
        
        for row in rows:
            store_id = row[0]
            store_name = row[1]
            
            if not store_name:
                error_count += 1
                continue
            
            try:
                # 店舗名から店舗コードを生成
                store_code = self.get_next_store_code_from_store_name(store_name)
                
                # 重複チェック（念のため）
                cursor.execute("SELECT COUNT(*) FROM stores WHERE store_code = ?", (store_code,))
                if cursor.fetchone()[0] > 0:
                    # 重複している場合は連番を増やす
                    max_code = self.get_max_store_code_for_prefix(store_code.split('-')[0])
                    if max_code:
                        prefix, number = max_code.rsplit('-', 1)
                        store_code = f"{prefix}-{int(number) + 1:02d}"
                    else:
                        store_code = f"{store_code.split('-')[0]}-01"
                
                # 店舗コードを更新
                cursor.execute("UPDATE stores SET store_code = ? WHERE id = ?", (store_code, store_id))
                updated_count += 1
            except Exception as e:
                print(f"店舗コード付与エラー (ID: {store_id}): {e}")
                error_count += 1
        
        conn.commit()
        
        return {
            'total': len(rows),
            'updated': updated_count,
            'errors': error_count
        }

    def reassign_store_codes_using_mappings(self) -> Dict[str, int]:
        """
        チェーン店コードマッピングを元に店舗コードを再付与する

        - 店舗名からチェーン店コードを判定（find_chain_code_by_store_name）
        - 既存の店舗コードがそのチェーン店コードで始まっていない場合、または空の場合にのみ再付与
        - 既存コードとの重複を避けるため、プレフィックスごとに現在の最大番号から順に採番する
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # store_code カラムの存在を保証
        try:
            cursor.execute("SELECT store_code FROM stores LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute("ALTER TABLE stores ADD COLUMN store_code TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                # 追加に失敗した場合はそのまま終了
                return {'total': 0, 'updated': 0, 'errors': 1}

        # 全店舗を取得
        cursor.execute("SELECT id, store_name, store_code FROM stores ORDER BY id")
        rows = cursor.fetchall()

        total = len(rows)
        updated = 0
        errors = 0

        # プレフィックスごとの次採番番号キャッシュ
        next_number_by_prefix: Dict[str, int] = {}

        for row in rows:
            store_id = row[0]
            store_name = row[1]
            current_code = row[2] or ""

            if not store_name:
                continue

            try:
                # 店舗名からチェーン店コード（プレフィックス）を取得
                prefix = self.find_chain_code_by_store_name(store_name)
                if not prefix:
                    # マッピングがない場合はフォールバックとしてプレフィックスを抽出
                    prefix = self._extract_store_prefix(store_name)

                if not prefix:
                    continue

                # 既存コードが既にこのプレフィックスで始まっている場合はそのままにする
                if current_code and str(current_code).startswith(f"{prefix}-"):
                    continue

                # このプレフィックスの次番号をキャッシュから取得（なければ最大値から計算）
                if prefix not in next_number_by_prefix:
                    max_code = self.get_max_store_code_for_prefix(prefix)
                    if max_code and '-' in max_code:
                        try:
                            _, num_part = max_code.rsplit('-', 1)
                            next_number_by_prefix[prefix] = int(num_part) + 1
                        except Exception:
                            next_number_by_prefix[prefix] = 1
                    else:
                        next_number_by_prefix[prefix] = 1

                next_num = next_number_by_prefix[prefix]
                new_code = f"{prefix}-{next_num:02d}"

                # 念のため重複チェック
                cursor.execute(
                    "SELECT COUNT(*) FROM stores WHERE store_code = ?",
                    (new_code,)
                )
                if cursor.fetchone()[0] > 0:
                    # すでに存在する場合は次の番号を試す
                    next_number_by_prefix[prefix] = next_num + 1
                    continue

                # 店舗コードを更新
                cursor.execute(
                    "UPDATE stores SET store_code = ? WHERE id = ?",
                    (new_code, store_id)
                )
                updated += 1
                next_number_by_prefix[prefix] = next_num + 1
            except Exception as e:
                print(f"店舗コード再付番エラー (ID: {store_id}): {e}")
                errors += 1

        conn.commit()

        return {
            'total': total,
            'updated': updated,
            'errors': errors
        }

