#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ルート訪問履歴データベース

ルート登録タブで保存された店舗訪問詳細を、日付・ルートコードをキーにスナップショットとして保存する。
- 同日・同ルートのデータは上書き（置き換え）
- 店舗訪問詳細の全カラムを保持し、将来的な分析や履歴参照で再利用できる
"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class RouteVisitDatabase:
    """ルート訪問履歴データベース操作クラス"""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "hirio.db")

        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def _init_database(self):
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS route_visit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_date TEXT NOT NULL,
                route_code TEXT NOT NULL,
                route_name TEXT NOT NULL,
                visit_order INTEGER NOT NULL,
                store_code TEXT,
                store_name TEXT,
                store_in_time TEXT,
                store_out_time TEXT,
                stay_duration REAL,
                travel_time_from_prev REAL,
                store_gross_profit REAL,
                store_item_count INTEGER,
                store_rating REAL,
                store_notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(route_date, route_code, visit_order)
            )
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_route_visit_logs_updated
            AFTER UPDATE ON route_visit_logs
            FOR EACH ROW
            BEGIN
                UPDATE route_visit_logs
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = NEW.id;
            END
        """)
        conn.commit()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ==================== 登録処理 ====================

    def replace_route_visits(self, route_date: str, route_code: str, route_name: str, visits: List[Dict[str, Any]]):
        """指定されたルートの日付・ルートコードに紐づく訪問データを丸ごと差し替える"""
        if not route_date or not route_code:
            return

        conn = self._get_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                "DELETE FROM route_visit_logs WHERE route_date = ? AND route_code = ?",
                (route_date, route_code)
            )

            insert_sql = """
                INSERT INTO route_visit_logs (
                    route_date, route_code, route_name, visit_order,
                    store_code, store_name, store_in_time, store_out_time,
                    stay_duration, travel_time_from_prev,
                    store_gross_profit, store_item_count, store_rating, store_notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """

            for visit in visits:
                cur.execute(insert_sql, (
                    route_date,
                    route_code,
                    route_name or route_code,
                    visit.get('visit_order'),
                    visit.get('store_code'),
                    visit.get('store_name'),
                    visit.get('store_in_time'),
                    visit.get('store_out_time'),
                    visit.get('stay_duration'),
                    visit.get('travel_time_from_prev'),
                    visit.get('store_gross_profit'),
                    visit.get('store_item_count'),
                    visit.get('store_rating'),
                    visit.get('store_notes'),
                ))

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def list_route_visits(self, route_date: Optional[str] = None, route_code: Optional[str] = None) -> List[Dict[str, Any]]:
        """保存済みのルート訪問履歴を取得"""
        conn = self._get_connection()
        cur = conn.cursor()

        query = "SELECT * FROM route_visit_logs WHERE 1=1"
        params: List[Any] = []
        if route_date:
            query += " AND route_date = ?"
            params.append(route_date)
        if route_code:
            query += " AND route_code = ?"
            params.append(route_code)
        query += " ORDER BY route_date DESC, visit_order ASC"

        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def list_route_codes(self) -> List[Dict[str, Any]]:
        """登録済みルートコードと名称の一覧を取得"""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT route_code, route_name
            FROM route_visit_logs
            ORDER BY route_name, route_code
        """)
        rows = cur.fetchall()
        return [dict(row) for row in rows]

    def delete_route_visits(self, route_date: str, route_code: str):
        """指定したルートの訪問データを削除"""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM route_visit_logs WHERE route_date = ? AND route_code = ?",
            (route_date, route_code)
        )
        conn.commit()

    def delete_visit_by_id(self, visit_id: int):
        """IDを指定して削除"""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM route_visit_logs WHERE id = ?", (visit_id,))
        conn.commit()

    def delete_all_visits(self):
        """全データを削除"""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM route_visit_logs")
        conn.commit()


if __name__ == "__main__":
    # 簡易動作確認
    db = RouteVisitDatabase()
    db.replace_route_visits(
        "2025-11-08",
        "K2",
        "川崎ルート",
        [
            {
                "visit_order": 1,
                "store_code": "K2-001",
                "store_name": "BOOKOFF",
                "store_in_time": "2025-11-08 10:00:00",
                "store_out_time": "2025-11-08 10:30:00",
                "stay_duration": 30,
                "travel_time_from_prev": 0,
                "store_gross_profit": 1200,
                "store_item_count": 3,
                "store_rating": 4,
                "store_notes": "テストデータ"
            }
        ]
    )
    print(db.list_route_visits("2025-11-08", "K2"))
    db.close()

