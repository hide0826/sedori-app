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

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None






