#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕訳帳データベース操作クラス

SQLite `python/desktop/data/hirio.db` に以下を作成:
- journal_entries: 仕訳帳エントリ
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class JournalDatabase:
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

        # 仕訳帳エントリ
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              transaction_date TEXT NOT NULL,
              debit_account TEXT NOT NULL,
              amount INTEGER NOT NULL,
              credit_account TEXT NOT NULL,
              description TEXT,
              invoice_number TEXT,
              tax_category TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # インデックス作成
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(transaction_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_debit ON journal_entries(debit_account)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_credit ON journal_entries(credit_account)")

        self.conn.commit()

        # 既存DBへのカラム追加（マイグレーション）
        def _ensure_column(table: str, column: str, coltype: str) -> None:
            try:
                cur.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cur.fetchall()]
                if column not in cols:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                    self.conn.commit()
            except Exception:
                pass

        _ensure_column("journal_entries", "image_url", "TEXT")

    def insert(self, entry: Dict[str, Any]) -> int:
        """仕訳エントリを挿入"""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO journal_entries 
            (transaction_date, debit_account, amount, credit_account, description, invoice_number, tax_category, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.get("transaction_date"),
                entry.get("debit_account"),
                entry.get("amount", 0),
                entry.get("credit_account"),
                entry.get("description"),
                entry.get("invoice_number"),
                entry.get("tax_category"),
                entry.get("image_url"),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def update(self, entry_id: int, entry: Dict[str, Any]) -> bool:
        """仕訳エントリを更新"""
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE journal_entries 
            SET transaction_date = ?, debit_account = ?, amount = ?, 
                credit_account = ?, description = ?, invoice_number = ?, 
                tax_category = ?, image_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                entry.get("transaction_date"),
                entry.get("debit_account"),
                entry.get("amount", 0),
                entry.get("credit_account"),
                entry.get("description"),
                entry.get("invoice_number"),
                entry.get("tax_category"),
                entry.get("image_url"),
                entry_id,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete(self, entry_id: int) -> bool:
        """仕訳エントリを削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_by_id(self, entry_id: int) -> Optional[Dict[str, Any]]:
        """IDで仕訳エントリを取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return None

    def list_all(self) -> List[Dict[str, Any]]:
        """すべての仕訳エントリを取得（日付順）"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM journal_entries ORDER BY transaction_date DESC, id DESC")
        return [dict(row) for row in cur.fetchall()]

    def list_by_date(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """期間で仕訳エントリを取得"""
        cur = self.conn.cursor()
        query = "SELECT * FROM journal_entries WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND transaction_date >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND transaction_date <= ?"
            params.append(end_date)
        
        query += " ORDER BY transaction_date DESC, id DESC"
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

