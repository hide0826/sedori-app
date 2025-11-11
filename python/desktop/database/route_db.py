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
                total_purchase_amount REAL,
                total_sales_amount REAL,
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
        for column, coltype in (
            ("total_purchase_amount", "REAL"),
            ("total_sales_amount", "REAL"),
        ):
            try:
                cursor.execute(f"ALTER TABLE route_summaries ADD COLUMN {column} {coltype} DEFAULT 0")
            except sqlite3.OperationalError:
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
                store_rating REAL,
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
                total_purchase_amount, total_sales_amount,
                total_working_hours, estimated_hourly_rate,
                total_gross_profit, total_item_count, purchase_success_rate, avg_purchase_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            route_data.get('total_purchase_amount'),
            route_data.get('total_sales_amount'),
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
                total_purchase_amount = ?,
                total_sales_amount = ?,
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
            route_data.get('total_purchase_amount'),
            route_data.get('total_sales_amount'),
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
    
    def get_route_summary_by_date_code(self, route_date: str, route_code: str) -> Optional[Dict[str, Any]]:
        """日付とルートコードでサマリーを取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM route_summaries WHERE route_date = ? AND route_code = ? ORDER BY id DESC LIMIT 1",
            (route_date, route_code)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    
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
        
        # updated_atはUTC保存のため、表示用にローカルタイムへ変換して返す
        query = (
            "SELECT id, route_date, route_code, departure_time, return_time, "
            "toll_fee_outbound, toll_fee_return, parking_fee, meal_cost, other_expenses, remarks, "
            "total_purchase_amount, total_sales_amount, "
            "total_working_hours, estimated_hourly_rate, total_gross_profit, total_item_count, "
            "purchase_success_rate, avg_purchase_price, created_at, updated_at, "
            "datetime(updated_at, 'localtime') AS updated_at_local "
            "FROM route_summaries WHERE 1=1"
        )
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
        result = []
        for row in rows:
            d = dict(row)
            # 置換: 表示用にローカルタイムを使う
            if 'updated_at_local' in d and d['updated_at_local']:
                d['updated_at'] = d['updated_at_local']
                del d['updated_at_local']
            result.append(d)
        return result
    
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
        """既存データの集計値を店舗訪問詳細から再計算して更新

        対象:
        - 総仕入点数 total_item_count
        - 総想定粗利 total_gross_profit
        - 平均仕入価格 avg_purchase_price (= total_gross_profit / total_item_count)
        - 総稼働時間 total_working_hours (= return_time - departure_time)
        - 想定時給 estimated_hourly_rate (= total_gross_profit / total_working_hours)

        既存データで0またはNULLの項目は再計算結果で埋める。
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # すべてのルートサマリーを取得
            cursor.execute("SELECT id, route_date, departure_time, return_time FROM route_summaries")
            route_rows = cursor.fetchall()
            
            updated_count = 0
            for row in route_rows:
                route_id = row[0]
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
                
                # 既存値を取得（NULL/0 の場合のみ上書きしたい項目があるため）
                cursor.execute("SELECT total_item_count, total_gross_profit, avg_purchase_price, total_working_hours, estimated_hourly_rate, departure_time, return_time FROM route_summaries WHERE id = ?", (route_id,))
                cur = cursor.fetchone() or [None]*7
                cur_total_items = cur[0]
                cur_total_profit = cur[1]
                cur_avg_price = cur[2]
                cur_working_hours = cur[3]
                cur_hourly_rate = cur[4]
                dep_str = cur[5]
                ret_str = cur[6]

                # 平均仕入価格（分母があれば計算）
                avg_price = None
                if total_items > 0:
                    avg_price = total_profit / total_items

                # 総稼働時間（出発/帰宅から計算）
                from datetime import datetime
                def _parse(dt_str):
                    if not dt_str:
                        return None
                    try:
                        return datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
                    except Exception:
                        try:
                            return datetime.strptime(str(dt_str).strip(), '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            return None
                dep_dt = _parse(dep_str)
                ret_dt = _parse(ret_str)
                working_hours = None
                if dep_dt and ret_dt and ret_dt >= dep_dt:
                    working_hours = (ret_dt - dep_dt).total_seconds() / 3600.0

                # 想定時給（分母があれば計算）
                hourly_rate = None
                if working_hours is not None and working_hours > 0:
                    hourly_rate = total_profit / working_hours if total_profit is not None else None

                # 更新値（既存がNULL/0のときのみ埋める）
                new_total_items = total_items if (cur_total_items is None or cur_total_items == 0) else cur_total_items
                new_total_profit = total_profit if (cur_total_profit is None or cur_total_profit == 0) else cur_total_profit
                new_avg_price = avg_price if (cur_avg_price is None or cur_avg_price == 0) else cur_avg_price
                new_working_hours = working_hours if (cur_working_hours is None or cur_working_hours == 0) else cur_working_hours
                new_hourly_rate = hourly_rate if (cur_hourly_rate is None or cur_hourly_rate == 0) else cur_hourly_rate

                # 変更がある場合のみUPDATE（不要なトリガー発火を防止）
                if any([
                    (cur_total_items or 0) != new_total_items,
                    (cur_total_profit or 0) != new_total_profit,
                    (cur_avg_price or 0) != (new_avg_price or 0),
                    (cur_working_hours or 0) != (new_working_hours or 0),
                    (cur_hourly_rate or 0) != (new_hourly_rate or 0)
                ]):
                    cursor.execute("""
                        UPDATE route_summaries
                        SET total_item_count = ?,
                            total_gross_profit = ?,
                            avg_purchase_price = ?,
                            total_working_hours = ?,
                            estimated_hourly_rate = ?
                        WHERE id = ?
                    """, (
                        new_total_items,
                        new_total_profit,
                        new_avg_price,
                        new_working_hours,
                        new_hourly_rate,
                        route_id,
                    ))
                    updated_count += 1
            
            conn.commit()
            return updated_count
            
        except Exception as e:
            print(f"総仕入点数・総想定粗利同期エラー: {e}")
            conn.rollback()
            return 0

