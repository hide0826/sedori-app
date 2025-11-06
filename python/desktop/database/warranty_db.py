#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保証書データベース操作クラス

SQLite `python/desktop/data/hirio.db` に `warranties` テーブルを作成。
- 保証書画像ファイル、OCR抽出した商品名、SKU とのマッチ結果などを保持。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class WarrantyDatabase:
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
            CREATE TABLE IF NOT EXISTS warranties (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              file_path TEXT NOT NULL,
              ocr_product_name TEXT,
              sku TEXT,
              matched_confidence REAL,
              notes TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_warranty_sku ON warranties(sku)")
        self.conn.commit()

    def insert_warranty(self, data: Dict[str, Any]) -> int:
        fields = ["file_path", "ocr_product_name", "sku", "matched_confidence", "notes"]
        placeholders = ",".join(["?"] * len(fields))
        cur = self.conn.cursor()
        cur.execute(
            f"INSERT INTO warranties ({','.join(fields)}) VALUES ({placeholders})",
            tuple(data.get(k) for k in fields),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_warranty(self, warranty_id: int, updates: Dict[str, Any]) -> bool:
        if not updates:
            return False
        set_parts = []
        params: List[Any] = []
        for k, v in updates.items():
            set_parts.append(f"{k} = ?")
            params.append(v)
        set_sql = ", ".join(set_parts) + ", updated_at = CURRENT_TIMESTAMP"
        params.append(warranty_id)
        cur = self.conn.cursor()
        cur.execute(f"UPDATE warranties SET {set_sql} WHERE id = ?", tuple(params))
        self.conn.commit()
        return cur.rowcount > 0

    def get_warranty(self, warranty_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM warranties WHERE id = ?", (warranty_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_by_sku(self, sku: str) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM warranties WHERE sku = ? ORDER BY id DESC", (sku,))
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


