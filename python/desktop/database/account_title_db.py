#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""勘定科目マスタ用データベース"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class AccountTitleDatabase:
    """勘定科目マスタを管理するシンプルなDBクラス"""

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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS account_titles (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE NOT NULL,
              sort_order INTEGER DEFAULT 0,
              note TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # 貸方勘定科目テーブル
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              card_name TEXT,
              last_four_digits TEXT,
              is_default INTEGER DEFAULT 0,
              sort_order INTEGER DEFAULT 0,
              note TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
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

        # デフォルトの貸方勘定科目を追加（初回のみ）
        cur.execute("SELECT COUNT(*) FROM credit_accounts")
        if cur.fetchone()[0] == 0:
            default_accounts = [
                ("現金", "", "", 1, 0, ""),
                ("預金", "", "", 0, 1, ""),
            ]
            for name, card_name, last_four, is_default, sort_order, note in default_accounts:
                cur.execute(
                    "INSERT INTO credit_accounts (name, card_name, last_four_digits, is_default, sort_order, note) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, card_name, last_four, is_default, sort_order, note)
                )
            self.conn.commit()

    # ===== CRUD =====
    def list_titles(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM account_titles ORDER BY sort_order ASC, name ASC")
        return [dict(r) for r in cur.fetchall()]
    
    def get_all_titles(self) -> List[Dict[str, Any]]:
        """list_titles()のエイリアス（互換性のため）"""
        return self.list_titles()

    def add_title(self, name: str, note: str = "") -> int:
        if not name.strip():
            raise ValueError("科目名は必須です")
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO account_titles (name, note) VALUES (?, ?)",
            (name.strip(), note.strip()),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_title(self, title_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM account_titles WHERE id = ?", (title_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ===== 貸方勘定科目 CRUD =====
    def list_credit_accounts(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM credit_accounts ORDER BY is_default DESC, sort_order ASC, name ASC")
        return [dict(r) for r in cur.fetchall()]
    
    def get_default_credit_account(self) -> Optional[Dict[str, Any]]:
        """デフォルトの貸方勘定科目を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM credit_accounts WHERE is_default = 1 ORDER BY sort_order ASC LIMIT 1")
        row = cur.fetchone()
        if row:
            return dict(row)
        return None
    
    def add_credit_account(self, name: str, card_name: str = "", last_four_digits: str = "", is_default: bool = False, note: str = "") -> int:
        if not name.strip():
            raise ValueError("科目名は必須です")
        cur = self.conn.cursor()
        # デフォルトを設定する場合、他のデフォルトを解除
        if is_default:
            cur.execute("UPDATE credit_accounts SET is_default = 0")
        cur.execute(
            "INSERT INTO credit_accounts (name, card_name, last_four_digits, is_default, note) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), card_name.strip(), last_four_digits.strip(), 1 if is_default else 0, note.strip()),
        )
        self.conn.commit()
        return cur.lastrowid
    
    def update_credit_account(self, account_id: int, name: str = None, card_name: str = None, last_four_digits: str = None, is_default: bool = None, note: str = None) -> bool:
        cur = self.conn.cursor()
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())
        if card_name is not None:
            updates.append("card_name = ?")
            params.append(card_name.strip())
        if last_four_digits is not None:
            updates.append("last_four_digits = ?")
            params.append(last_four_digits.strip())
        if is_default is not None:
            # デフォルトを設定する場合、他のデフォルトを解除
            if is_default:
                cur.execute("UPDATE credit_accounts SET is_default = 0")
            updates.append("is_default = ?")
            params.append(1 if is_default else 0)
        if note is not None:
            updates.append("note = ?")
            params.append(note.strip())
        
        if not updates:
            return False
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(account_id)
        
        cur.execute(f"UPDATE credit_accounts SET {', '.join(updates)} WHERE id = ?", params)
        self.conn.commit()
        return cur.rowcount > 0
    
    def delete_credit_account(self, account_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM credit_accounts WHERE id = ?", (account_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None






