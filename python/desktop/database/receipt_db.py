#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシート・マッチ学習 データベース操作クラス

SQLite `python/desktop/data/hirio.db` に以下を作成:
- receipts: レシートOCR結果およびメタデータ
- receipt_match_learnings: 店舗名の学習辞書（生テキスト→店舗コード）
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ReceiptDatabase:
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

        # レシート本体
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              file_path TEXT NOT NULL,
              purchase_date TEXT,            -- OCR抽出 or 手動
              store_name_raw TEXT,           -- OCR生文字列
              store_code TEXT,               -- 店舗マスタにマッチしたコード
              subtotal INTEGER,
              tax INTEGER,
              discount_amount INTEGER,
              total_amount INTEGER,
              paid_amount INTEGER,
              currency TEXT,
              ocr_provider TEXT,             -- 'tesseract' / 'gcv' など
              ocr_text TEXT,                 -- フルテキスト保管
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 学習辞書（店舗名揺れ対応）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS receipt_match_learnings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              receipt_store_name_raw TEXT NOT NULL,
              matched_store_code TEXT NOT NULL,
              weight INTEGER DEFAULT 1,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(receipt_store_name_raw, matched_store_code)
            )
            """
        )

        # インデックス
        cur.execute("CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(purchase_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_receipts_store_code ON receipts(store_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_receipt_learn_raw ON receipt_match_learnings(receipt_store_name_raw)")

        self.conn.commit()

    # ==== receipts 操作 ====
    def insert_receipt(self, data: Dict[str, Any]) -> int:
        fields = [
            "file_path","purchase_date","store_name_raw","store_code","subtotal","tax",
            "discount_amount","total_amount","paid_amount","currency","ocr_provider","ocr_text",
        ]
        placeholders = ",".join(["?"] * len(fields))
        cur = self.conn.cursor()
        cur.execute(
            f"INSERT INTO receipts ({','.join(fields)}) VALUES ({placeholders})",
            tuple(data.get(k) for k in fields),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_receipt(self, receipt_id: int, updates: Dict[str, Any]) -> bool:
        if not updates:
            return False
        set_parts = []
        params: List[Any] = []
        for k, v in updates.items():
            set_parts.append(f"{k} = ?")
            params.append(v)
        set_sql = ", ".join(set_parts) + ", updated_at = CURRENT_TIMESTAMP"
        params.append(receipt_id)
        cur = self.conn.cursor()
        cur.execute(f"UPDATE receipts SET {set_sql} WHERE id = ?", tuple(params))
        self.conn.commit()
        return cur.rowcount > 0

    def get_receipt(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def find_by_date_and_store(self, purchase_date: str, store_code: Optional[str] = None) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        if store_code:
            cur.execute(
                "SELECT * FROM receipts WHERE purchase_date = ? AND store_code = ? ORDER BY id DESC",
                (purchase_date, store_code),
            )
        else:
            cur.execute(
                "SELECT * FROM receipts WHERE purchase_date = ? ORDER BY id DESC",
                (purchase_date,),
            )
        return [dict(r) for r in cur.fetchall()]

    # ==== 学習 ====
    def learn_store_match(self, raw_name: str, store_code: str, weight: int = 1) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO receipt_match_learnings (receipt_store_name_raw, matched_store_code, weight, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(receipt_store_name_raw, matched_store_code)
            DO UPDATE SET weight = weight + excluded.weight, updated_at = CURRENT_TIMESTAMP
            """,
            (raw_name, store_code, weight),
        )
        self.conn.commit()

    def guess_store_code(self, raw_name: str) -> Optional[Tuple[str, int]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT matched_store_code, weight
            FROM receipt_match_learnings
            WHERE receipt_store_name_raw = ?
            ORDER BY weight DESC
            LIMIT 1
            """,
            (raw_name,),
        )
        row = cur.fetchone()
        if row:
            return (row[0], row[1])
        return None

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


