#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
経費管理データベース操作クラス

SQLite `python/desktop/data/hirio.db` に `expenses` テーブルを作成し、
経費情報の保存・更新・参照を提供する。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class ExpenseDatabase:
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
        
        # expenses テーブル（経費情報）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              expense_date TEXT NOT NULL,
              expense_category TEXT NOT NULL,  -- '消耗品費', '旅費交通費', '通信費', '光熱費', '広告宣伝費', 'その他'
              account_title TEXT,              -- 勘定科目（税理士用）
              store_name TEXT,                 -- 支払先名
              store_code TEXT,                 -- 店舗マスタと紐付け可能
              amount INTEGER NOT NULL,          -- 金額
              quantity INTEGER DEFAULT 1,      -- 数量（ダンボール10個など）
              unit_price INTEGER,              -- 単価
              payment_method TEXT,             -- '現金', 'クレジットカード', 'QR決済', '電子マネー' など
              receipt_id INTEGER,               -- receiptsテーブルと紐付け
              receipt_file_path TEXT,          -- レシート画像パス
              memo TEXT,                       -- メモ
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (receipt_id) REFERENCES receipts(id)
            )
            """
        )

        # インデックス作成
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(expense_category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_store_code ON expenses(store_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_receipt_id ON expenses(receipt_id)")

        self.conn.commit()

        # 既存DBへのカラム追加（マイグレーション）
        self._migrate_columns(cur)

    def _migrate_columns(self, cur: sqlite3.Cursor) -> None:
        """不足しているカラムを追加する"""
        cur.execute("PRAGMA table_info(expenses)")
        existing_cols = {row["name"] for row in cur.fetchall()}

        # 追加すべきカラム定義 (name, type)
        new_columns = [
            ("account_title", "TEXT"),
            ("store_code", "TEXT"),
            ("quantity", "INTEGER DEFAULT 1"),
            ("unit_price", "INTEGER"),
            ("payment_method", "TEXT"),
            ("receipt_file_path", "TEXT"),
        ]

        for col_name, col_def in new_columns:
            if col_name not in existing_cols:
                try:
                    cur.execute(f"ALTER TABLE expenses ADD COLUMN {col_name} {col_def}")
                except Exception as e:
                    print(f"Error adding column {col_name}: {e}")
        
        self.conn.commit()

    # ========= 基本操作 =========
    def upsert(self, expense: Dict[str, Any]) -> int:
        """
        経費情報を挿入/更新する
        
        Args:
            expense: 経費情報の辞書
        
        Returns:
            挿入/更新されたレコードのID
        """
        if not expense.get("expense_date"):
            raise ValueError("expense_date is required")
        if not expense.get("expense_category"):
            raise ValueError("expense_category is required")
        if expense.get("amount") is None:
            raise ValueError("amount is required")

        # 既存判定（IDがあれば更新）
        expense_id = expense.get("id")
        if expense_id:
            existing = self.get_by_id(expense_id)
            if existing:
                # 更新
                fields = [
                    "expense_date", "expense_category", "account_title",
                    "store_name", "store_code", "amount", "quantity",
                    "unit_price", "payment_method", "receipt_id",
                    "receipt_file_path", "memo"
                ]
                set_clause = ",".join([f"{k}=?" for k in fields]) + ", updated_at=CURRENT_TIMESTAMP"
                update_values = [expense.get(k) for k in fields] + [expense_id]
                cur = self.conn.cursor()
                cur.execute(f"UPDATE expenses SET {set_clause} WHERE id=?", update_values)
                self.conn.commit()
                return expense_id

        # 挿入
        fields = [
            "expense_date", "expense_category", "account_title",
            "store_name", "store_code", "amount", "quantity",
            "unit_price", "payment_method", "receipt_id",
            "receipt_file_path", "memo"
        ]
        values = [expense.get(k) for k in fields]
        
        cur = self.conn.cursor()
        placeholders = ",".join(["?"] * len(fields))
        cur.execute(
            f"INSERT INTO expenses ({','.join(fields)}) VALUES ({placeholders})",
            values,
        )
        expense_id = cur.lastrowid
        self.conn.commit()
        return expense_id

    def get_by_id(self, expense_id: int) -> Optional[Dict[str, Any]]:
        """IDで経費情報を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        """全経費情報を取得（更新日時の新しい順）"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM expenses ORDER BY IFNULL(updated_at, created_at) DESC, expense_date DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_date(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """期間で経費情報を取得"""
        cur = self.conn.cursor()
        where = []
        params: List[Any] = []
        if start_date:
            where.append("expense_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("expense_date <= ?")
            params.append(end_date)
        sql = "SELECT * FROM expenses"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY expense_date DESC, id DESC"
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def list_by_category(self, category: str) -> List[Dict[str, Any]]:
        """カテゴリで経費情報を取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM expenses WHERE expense_category = ? ORDER BY expense_date DESC",
            (category,)
        )
        return [dict(r) for r in cur.fetchall()]

    def delete(self, expense_id: int) -> bool:
        """IDで経費情報を削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None





