#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
販売履歴データベース操作クラス

SQLite データベース `python/desktop/data/hirio.db` 内に `sales` テーブルを作成し、
販売情報の保存・更新・参照を提供する。

主な用途:
- 販売情報の管理（いつ・いくらで売れたか・手数料など）
- 仕入履歴(purchases)への参照
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class SalesDatabase:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "hirio.db")
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
        
        # sales テーブル（販売履歴）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sales (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              purchase_id INTEGER,
              inventory_status_id INTEGER,
              sku TEXT NOT NULL,
              sale_date TEXT NOT NULL,
              sales_method TEXT NOT NULL,
              platform TEXT NOT NULL,
              sale_price INTEGER NOT NULL,
              platform_fee INTEGER DEFAULT 0,
              shipping_fee INTEGER DEFAULT 0,
              fba_fee INTEGER DEFAULT 0,
              storage_fee INTEGER DEFAULT 0,
              other_fees INTEGER DEFAULT 0,
              net_profit INTEGER,
              order_id TEXT,
              buyer_name TEXT,
              transaction_method TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (purchase_id) REFERENCES purchases(id),
              FOREIGN KEY (inventory_status_id) REFERENCES inventory_status(id)
            )
            """
        )

        # インデックス作成
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_sku ON sales(sku)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_sale_date ON sales(sale_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_purchase_id ON sales(purchase_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_platform ON sales(platform)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_sales_method ON sales(sales_method)")

        self.conn.commit()

    # ========= 基本操作 =========
    def insert(self, sale: Dict[str, Any]) -> int:
        """
        販売情報を挿入する
        
        Args:
            sale: 販売情報の辞書
        
        Returns:
            挿入されたレコードのID
        """
        if not sale.get("sku") or not sale.get("sale_date"):
            raise ValueError("sku and sale_date are required")

        # net_profitを計算（指定されていない場合）
        if sale.get("net_profit") is None:
            net_profit = (
                sale.get("sale_price", 0) -
                sale.get("platform_fee", 0) -
                sale.get("shipping_fee", 0) -
                sale.get("fba_fee", 0) -
                sale.get("storage_fee", 0) -
                sale.get("other_fees", 0)
            )
            sale["net_profit"] = net_profit

        fields = [
            "purchase_id", "inventory_status_id", "sku", "sale_date",
            "sales_method", "platform", "sale_price", "platform_fee",
            "shipping_fee", "fba_fee", "storage_fee", "other_fees",
            "net_profit", "order_id", "buyer_name", "transaction_method"
        ]
        values = [sale.get(k) for k in fields]

        cur = self.conn.cursor()
        placeholders = ",".join(["?"] * len(fields))
        cur.execute(
            f"INSERT INTO sales ({','.join(fields)}) VALUES ({placeholders})",
            values,
        )
        sale_id = cur.lastrowid
        self.conn.commit()
        return sale_id

    def get_by_id(self, sale_id: int) -> Optional[Dict[str, Any]]:
        """IDで販売情報を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM sales WHERE id = ?", (sale_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_sku(self, sku: str) -> List[Dict[str, Any]]:
        """SKUで販売情報を取得（複数件の可能性）"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM sales WHERE sku = ? ORDER BY sale_date DESC",
            (sku,)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_all(self) -> List[Dict[str, Any]]:
        """全販売情報を取得（販売日の新しい順）"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM sales ORDER BY sale_date DESC, id DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_date(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """期間で販売情報を取得"""
        cur = self.conn.cursor()
        where = []
        params: List[Any] = []
        if start_date:
            where.append("sale_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("sale_date <= ?")
            params.append(end_date)
        sql = "SELECT * FROM sales"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY sale_date DESC, id DESC"
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def list_by_platform(self, platform: str) -> List[Dict[str, Any]]:
        """プラットフォームで販売情報を取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM sales WHERE platform = ? ORDER BY sale_date DESC",
            (platform,)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_sales_method(self, sales_method: str) -> List[Dict[str, Any]]:
        """販売方法で販売情報を取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM sales WHERE sales_method = ? ORDER BY sale_date DESC",
            (sales_method,)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_summary_by_period(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """期間別の販売サマリーを取得"""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT 
                COUNT(*) as sale_count,
                SUM(sale_price) as total_sales,
                SUM(net_profit) as total_profit,
                AVG(net_profit) as avg_profit
            FROM sales
            WHERE sale_date >= ? AND sale_date <= ?
            """,
            (start_date, end_date)
        )
        row = cur.fetchone()
        return dict(row) if row else {
            "sale_count": 0,
            "total_sales": 0,
            "total_profit": 0,
            "avg_profit": 0
        }

    def delete(self, sale_id: int) -> bool:
        """IDで販売情報を削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

