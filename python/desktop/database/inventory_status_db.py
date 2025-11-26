#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在庫状態管理データベース操作クラス

SQLite データベース `python/desktop/data/hirio.db` 内に `inventory_status` テーブルを作成し、
在庫状態（未出品・出品中・寝かせ・販売済みなど）の管理を提供する。

主な用途:
- 在庫状態の管理
- 販売方法・プラットフォーム情報の管理
- 仕入履歴(purchases)への参照
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class InventoryStatusDatabase:
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
        
        # inventory_status テーブル（在庫状態管理）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_status (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              purchase_id INTEGER,
              sku TEXT UNIQUE NOT NULL,
              status TEXT NOT NULL,
              sales_method TEXT,
              platform TEXT,
              listed_date TEXT,
              planned_price INTEGER,
              current_price INTEGER,
              price_trace INTEGER DEFAULT 0,
              notes TEXT,
              sales_id INTEGER,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (purchase_id) REFERENCES purchases(id),
              FOREIGN KEY (sales_id) REFERENCES sales(id)
            )
            """
        )

        # インデックス作成
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_status_sku ON inventory_status(sku)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_status_status ON inventory_status(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_status_sales_method ON inventory_status(sales_method)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_status_platform ON inventory_status(platform)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_status_purchase_id ON inventory_status(purchase_id)")

        self.conn.commit()

    # ========= 基本操作 =========
    def upsert(self, status: Dict[str, Any]) -> int:
        """
        在庫状態を挿入/更新する
        
        Args:
            status: 在庫状態情報の辞書
        
        Returns:
            挿入/更新されたレコードのID
        """
        if not status.get("sku") or not status.get("status"):
            raise ValueError("sku and status are required")

        # 既存判定
        existing = self.get_by_sku(status["sku"])

        fields = [
            "purchase_id", "sku", "status", "sales_method", "platform",
            "listed_date", "planned_price", "current_price", "price_trace",
            "notes", "sales_id"
        ]
        values = [status.get(k) for k in fields]

        cur = self.conn.cursor()
        if existing:
            # 更新（初回出品日は保持）
            if existing.get("listed_date") and not status.get("listed_date"):
                # 既存のlisted_dateを保持
                status["listed_date"] = existing["listed_date"]
            
            set_clause = ",".join([f"{k}=?" for k in fields if k != "sku"]) + ", updated_at=CURRENT_TIMESTAMP"
            update_values = [status.get(k) for k in fields if k != "sku"] + [status["sku"]]
            cur.execute(f"UPDATE inventory_status SET {set_clause} WHERE sku=?", update_values)
            status_id = existing["id"]
        else:
            # 挿入
            placeholders = ",".join(["?"] * len(fields))
            cur.execute(
                f"INSERT INTO inventory_status ({','.join(fields)}) VALUES ({placeholders})",
                values,
            )
            status_id = cur.lastrowid
        
        self.conn.commit()
        return status_id

    def get_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """SKUで在庫状態を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM inventory_status WHERE sku = ?", (sku,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_id(self, status_id: int) -> Optional[Dict[str, Any]]:
        """IDで在庫状態を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM inventory_status WHERE id = ?", (status_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        """全在庫状態を取得（更新日時の新しい順）"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM inventory_status ORDER BY IFNULL(updated_at, created_at) DESC, sku DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_status(self, status: str) -> List[Dict[str, Any]]:
        """在庫状態で取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM inventory_status WHERE status = ? ORDER BY updated_at DESC",
            (status,)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_sales_method(self, sales_method: str) -> List[Dict[str, Any]]:
        """販売方法で取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM inventory_status WHERE sales_method = ? ORDER BY updated_at DESC",
            (sales_method,)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_platform(self, platform: str) -> List[Dict[str, Any]]:
        """プラットフォームで取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM inventory_status WHERE platform = ? ORDER BY updated_at DESC",
            (platform,)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_filtered(
        self,
        statuses: Optional[List[str]] = None,
        sales_methods: Optional[List[str]] = None,
        platforms: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        複数条件で在庫状態を取得（フィルタ用）
        
        Args:
            statuses: 在庫状態のリスト（例: ['未出品', '出品中']）
            sales_methods: 販売方法のリスト（例: ['FBA', '自己発送']）
            platforms: プラットフォームのリスト（例: ['Amazon', 'メルカリ']）
        
        Returns:
            フィルタされた在庫状態のリスト
        """
        cur = self.conn.cursor()
        where = []
        params: List[Any] = []
        
        if statuses:
            placeholders = ",".join(["?"] * len(statuses))
            where.append(f"status IN ({placeholders})")
            params.extend(statuses)
        
        if sales_methods:
            placeholders = ",".join(["?"] * len(sales_methods))
            where.append(f"sales_method IN ({placeholders})")
            params.extend(sales_methods)
        
        if platforms:
            placeholders = ",".join(["?"] * len(platforms))
            where.append(f"platform IN ({placeholders})")
            params.extend(platforms)
        
        sql = "SELECT * FROM inventory_status"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC, sku DESC"
        
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def update_status(self, sku: str, status: str, **kwargs) -> bool:
        """
        在庫状態を更新する
        
        Args:
            sku: SKU
            status: 新しい在庫状態
            **kwargs: その他の更新フィールド
        """
        cur = self.conn.cursor()
        set_parts = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: List[Any] = [status]
        
        for key, value in kwargs.items():
            if value is not None:
                set_parts.append(f"{key} = ?")
                params.append(value)
        
        params.append(sku)
        cur.execute(
            f"UPDATE inventory_status SET {', '.join(set_parts)} WHERE sku = ?",
            params
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete(self, sku: str) -> bool:
        """SKUで在庫状態を削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inventory_status WHERE sku = ?", (sku,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

