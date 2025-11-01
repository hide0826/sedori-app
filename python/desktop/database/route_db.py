#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルートサマリーデータベース操作クラス

SQLiteデータベースを使用したルートサマリー管理
- route_summaries テーブル: ルートサマリー情報
- store_visit_details テーブル: 店舗訪問詳細情報
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class RouteDatabase:
    """ルートサマリーデータベース操作クラス"""
    
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
        
        # route_summaries テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS route_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_date DATE NOT NULL,
                route_code TEXT NOT NULL,
                departure_time DATETIME,
                return_time DATETIME,
                toll_fee_outbound REAL,
                toll_fee_return REAL,
                parking_fee REAL,
                meal_cost REAL,
                other_expenses REAL,
                remarks TEXT,
                total_working_hours REAL,
                estimated_hourly_rate REAL,
                total_gross_profit REAL,
                total_item_count INTEGER,
                purchase_success_rate REAL,
                avg_purchase_price REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # total_item_countカラムが存在しない場合は追加（マイグレーション）
        try:
            cursor.execute("ALTER TABLE route_summaries ADD COLUMN total_item_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            # カラムが既に存在する場合はスキップ
            pass
        
        # store_visit_details テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS store_visit_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_summary_id INTEGER,
                store_code TEXT NOT NULL,
                visit_order INTEGER,
                store_in_time DATETIME,
                store_out_time DATETIME,
                stay_duration REAL,
                travel_time_from_prev REAL,
                distance_from_prev REAL,
                store_gross_profit REAL,
                store_item_count INTEGER,
                purchase_success INTEGER DEFAULT 0,
                no_purchase_reason TEXT,
                store_rating INTEGER,
                store_notes TEXT,
                next_visit_recommendation TEXT,
                category_breakdown TEXT,
                competitor_present INTEGER DEFAULT 0,
                inventory_level TEXT,
                trouble_occurred INTEGER DEFAULT 0,
                trouble_details TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (route_summary_id) REFERENCES route_summaries(id) ON DELETE CASCADE
            )
        """)
        
        # updated_atを自動更新するトリガー（route_summaries）
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_route_summaries_timestamp 
            AFTER UPDATE ON route_summaries
            FOR EACH ROW
            BEGIN
                UPDATE route_summaries SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)
        
        # updated_atを自動更新するトリガー（store_visit_details）
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_store_visit_details_timestamp 
            AFTER UPDATE ON store_visit_details
            FOR EACH ROW
            BEGIN
                UPDATE store_visit_details SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)
        
        conn.commit()
    
    def close(self):
        """データベース接続を閉じる"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    # ==================== route_summaries テーブル操作 ====================
    
    def add_route_summary(self, route_data: Dict[str, Any]) -> int:
        """ルートサマリーを追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO route_summaries (
                route_date, route_code, departure_time, return_time,
                toll_fee_outbound, toll_fee_return, parking_fee,
                meal_cost, other_expenses, remarks,
                total_working_hours, estimated_hourly_rate,
                total_gross_profit, total_item_count, purchase_success_rate, avg_purchase_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            route_data.get('route_date'),
            route_data.get('route_code'),
            route_data.get('departure_time'),
            route_data.get('return_time'),
            route_data.get('toll_fee_outbound'),
            route_data.get('toll_fee_return'),
            route_data.get('parking_fee'),
            route_data.get('meal_cost'),
            route_data.get('other_expenses'),
            route_data.get('remarks'),
            route_data.get('total_working_hours'),
            route_data.get('estimated_hourly_rate'),
            route_data.get('total_gross_profit'),
            route_data.get('total_item_count'),
            route_data.get('purchase_success_rate'),
            route_data.get('avg_purchase_price')
        ))
        
        conn.commit()
        return cursor.lastrowid
    
    def update_route_summary(self, route_id: int, route_data: Dict[str, Any]) -> bool:
        """ルートサマリーを更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE route_summaries SET
                route_date = ?,
                route_code = ?,
                departure_time = ?,
                return_time = ?,
                toll_fee_outbound = ?,
                toll_fee_return = ?,
                parking_fee = ?,
                meal_cost = ?,
                other_expenses = ?,
                remarks = ?,
                total_working_hours = ?,
                estimated_hourly_rate = ?,
                total_gross_profit = ?,
                total_item_count = ?,
                purchase_success_rate = ?,
                avg_purchase_price = ?
            WHERE id = ?
        """, (
            route_data.get('route_date'),
            route_data.get('route_code'),
            route_data.get('departure_time'),
            route_data.get('return_time'),
            route_data.get('toll_fee_outbound'),
            route_data.get('toll_fee_return'),
            route_data.get('parking_fee'),
            route_data.get('meal_cost'),
            route_data.get('other_expenses'),
            route_data.get('remarks'),
            route_data.get('total_working_hours'),
            route_data.get('estimated_hourly_rate'),
            route_data.get('total_gross_profit'),
            route_data.get('total_item_count'),
            route_data.get('purchase_success_rate'),
            route_data.get('avg_purchase_price'),
            route_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_route_summary(self, route_id: int) -> bool:
        """ルートサマリーを削除（関連する店舗訪問詳細も削除される）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM route_summaries WHERE id = ?", (route_id,))
        conn.commit()
        
        return cursor.rowcount > 0
    
    def get_route_summary(self, route_id: int) -> Optional[Dict[str, Any]]:
        """ルートサマリーを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM route_summaries WHERE id = ?", (route_id,))
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return None
    
    def list_route_summaries(self, start_date: Optional[str] = None, end_date: Optional[str] = None, route_code: Optional[str] = None) -> List[Dict[str, Any]]:
        """ルートサマリー一覧を取得（検索対応）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = "SELECT * FROM route_summaries WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND route_date >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND route_date <= ?"
            params.append(end_date)
        
        if route_code:
            query += " AND route_code = ?"
            params.append(route_code)
        
        query += " ORDER BY route_date DESC, id DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    # ==================== store_visit_details テーブル操作 ====================
    
    def add_store_visit(self, visit_data: Dict[str, Any]) -> int:
        """店舗訪問詳細を追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # category_breakdownをJSON文字列に変換
        category_breakdown_json = None
        if visit_data.get('category_breakdown'):
            category_breakdown_json = json.dumps(visit_data.get('category_breakdown'), ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO store_visit_details (
                route_summary_id, store_code, visit_order,
                store_in_time, store_out_time, stay_duration,
                travel_time_from_prev, distance_from_prev,
                store_gross_profit, store_item_count,
                purchase_success, no_purchase_reason,
                store_rating, store_notes, next_visit_recommendation,
                category_breakdown, competitor_present,
                inventory_level, trouble_occurred, trouble_details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            visit_data.get('route_summary_id'),
            visit_data.get('store_code'),
            visit_data.get('visit_order'),
            visit_data.get('store_in_time'),
            visit_data.get('store_out_time'),
            visit_data.get('stay_duration'),
            visit_data.get('travel_time_from_prev'),
            visit_data.get('distance_from_prev'),
            visit_data.get('store_gross_profit'),
            visit_data.get('store_item_count'),
            1 if visit_data.get('purchase_success') else 0,
            visit_data.get('no_purchase_reason'),
            visit_data.get('store_rating'),
            visit_data.get('store_notes'),
            visit_data.get('next_visit_recommendation'),
            category_breakdown_json,
            1 if visit_data.get('competitor_present') else 0,
            visit_data.get('inventory_level'),
            1 if visit_data.get('trouble_occurred') else 0,
            visit_data.get('trouble_details')
        ))
        
        conn.commit()
        return cursor.lastrowid
    
    def update_store_visit(self, visit_id: int, visit_data: Dict[str, Any]) -> bool:
        """店舗訪問詳細を更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # category_breakdownをJSON文字列に変換
        category_breakdown_json = None
        if visit_data.get('category_breakdown'):
            category_breakdown_json = json.dumps(visit_data.get('category_breakdown'), ensure_ascii=False)
        
        cursor.execute("""
            UPDATE store_visit_details SET
                route_summary_id = ?,
                store_code = ?,
                visit_order = ?,
                store_in_time = ?,
                store_out_time = ?,
                stay_duration = ?,
                travel_time_from_prev = ?,
                distance_from_prev = ?,
                store_gross_profit = ?,
                store_item_count = ?,
                purchase_success = ?,
                no_purchase_reason = ?,
                store_rating = ?,
                store_notes = ?,
                next_visit_recommendation = ?,
                category_breakdown = ?,
                competitor_present = ?,
                inventory_level = ?,
                trouble_occurred = ?,
                trouble_details = ?
            WHERE id = ?
        """, (
            visit_data.get('route_summary_id'),
            visit_data.get('store_code'),
            visit_data.get('visit_order'),
            visit_data.get('store_in_time'),
            visit_data.get('store_out_time'),
            visit_data.get('stay_duration'),
            visit_data.get('travel_time_from_prev'),
            visit_data.get('distance_from_prev'),
            visit_data.get('store_gross_profit'),
            visit_data.get('store_item_count'),
            1 if visit_data.get('purchase_success') else 0,
            visit_data.get('no_purchase_reason'),
            visit_data.get('store_rating'),
            visit_data.get('store_notes'),
            visit_data.get('next_visit_recommendation'),
            category_breakdown_json,
            1 if visit_data.get('competitor_present') else 0,
            visit_data.get('inventory_level'),
            1 if visit_data.get('trouble_occurred') else 0,
            visit_data.get('trouble_details'),
            visit_id
        ))
        
        conn.commit()
        return cursor.rowcount > 0
    
    def delete_store_visit(self, visit_id: int) -> bool:
        """店舗訪問詳細を削除"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM store_visit_details WHERE id = ?", (visit_id,))
        conn.commit()
        
        return cursor.rowcount > 0
    
    def get_store_visit(self, visit_id: int) -> Optional[Dict[str, Any]]:
        """店舗訪問詳細を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM store_visit_details WHERE id = ?", (visit_id,))
        row = cursor.fetchone()
        
        if row:
            return self._row_to_dict(row)
        return None
    
    def get_store_visits_by_route(self, route_summary_id: int) -> List[Dict[str, Any]]:
        """ルートサマリーIDに紐づく店舗訪問詳細一覧を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM store_visit_details WHERE route_summary_id = ? ORDER BY visit_order",
            (route_summary_id,)
        )
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Rowを辞書に変換（category_breakdownをパース）"""
        visit_dict = dict(row)
        
        # category_breakdownをJSONから辞書に変換
        if visit_dict.get('category_breakdown'):
            try:
                visit_dict['category_breakdown'] = json.loads(visit_dict['category_breakdown'])
            except json.JSONDecodeError:
                visit_dict['category_breakdown'] = {}
        else:
            visit_dict['category_breakdown'] = {}
        
        # BOOLEAN値を変換
        visit_dict['purchase_success'] = bool(visit_dict.get('purchase_success', 0))
        visit_dict['competitor_present'] = bool(visit_dict.get('competitor_present', 0))
        visit_dict['trouble_occurred'] = bool(visit_dict.get('trouble_occurred', 0))
        
        return visit_dict
    
    # ==================== ユーティリティ ====================
    
    def get_statistics(self) -> Dict[str, Any]:
        """統計情報を取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # ルートサマリー総数
        cursor.execute("SELECT COUNT(*) FROM route_summaries")
        total_routes = cursor.fetchone()[0]
        
        # 店舗訪問総数
        cursor.execute("SELECT COUNT(*) FROM store_visit_details")
        total_visits = cursor.fetchone()[0]
        
        # 平均時給
        cursor.execute("SELECT AVG(estimated_hourly_rate) FROM route_summaries WHERE estimated_hourly_rate IS NOT NULL")
        avg_hourly_rate = cursor.fetchone()[0] or 0
        
        # 総粗利
        cursor.execute("SELECT SUM(total_gross_profit) FROM route_summaries WHERE total_gross_profit IS NOT NULL")
        total_gross_profit = cursor.fetchone()[0] or 0
        
        return {
            'total_routes': total_routes,
            'total_visits': total_visits,
            'avg_hourly_rate': avg_hourly_rate,
            'total_gross_profit': total_gross_profit
        }
    
    def sync_total_item_count_from_visits(self):
        """既存データの総仕入点数と総想定粗利を店舗訪問詳細から集計して更新"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # すべてのルートサマリーを取得
            cursor.execute("SELECT id FROM route_summaries")
            route_ids = [row[0] for row in cursor.fetchall()]
            
            updated_count = 0
            for route_id in route_ids:
                # 店舗訪問詳細から総仕入点数を集計
                cursor.execute("""
                    SELECT SUM(store_item_count) AS total_items,
                           SUM(store_gross_profit) AS total_profit
                    FROM store_visit_details
                    WHERE route_summary_id = ?
                """, (route_id,))
                
                result = cursor.fetchone()
                total_items = int(result[0]) if result and result[0] else 0
                total_profit = float(result[1]) if result and result[1] else 0
                
                # 総仕入点数と総想定粗利を更新
                cursor.execute("""
                    UPDATE route_summaries
                    SET total_item_count = ?, total_gross_profit = ?
                    WHERE id = ?
                """, (total_items, total_profit, route_id))
                
                if total_items > 0 or total_profit > 0:
                    updated_count += 1
            
            conn.commit()
            return updated_count
            
        except Exception as e:
            print(f"総仕入点数・総想定粗利同期エラー: {e}")
            conn.rollback()
            return 0

