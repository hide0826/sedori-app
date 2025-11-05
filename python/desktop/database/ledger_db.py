#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古物台帳用 SQLite アクセス

- purchase_rows: 取り込み/ドラフト編集用
- classification_cache: 品目自動入力キャッシュ
- ledger_entries: 確定台帳エントリ
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class LedgerDatabase:
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
            CREATE TABLE IF NOT EXISTS purchase_rows (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              import_batch_id TEXT,
              purchased_at TEXT,
              store_name TEXT,
              sku TEXT, asin TEXT, jan TEXT, title TEXT, brand TEXT, model TEXT,
              qty INTEGER, unit_price INTEGER, tax_type TEXT, notes TEXT,
              status TEXT DEFAULT 'imported',
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS classification_cache (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              product_key TEXT UNIQUE,
              kobutsu_kind TEXT, hinmoku TEXT, hinmei TEXT,
              confidence REAL DEFAULT 0,
              last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              memo TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              entry_date TEXT,
              counterparty_type TEXT,
              counterparty_name TEXT,
              receipt_no TEXT,
              platform TEXT,
              platform_order_id TEXT,
              platform_user TEXT,
              person_name TEXT,
              person_address TEXT,
              id_type TEXT,
              id_number TEXT,
              id_checked_on TEXT,
              id_checked_by TEXT,
              id_proof_ref TEXT,
              kobutsu_kind TEXT, hinmoku TEXT, hinmei TEXT,
              qty INTEGER, unit_price INTEGER, amount INTEGER,
              identifier TEXT,
              notes TEXT,
              correction_of INTEGER,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # index
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_entry_date ON ledger_entries(entry_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ledger_kobutsu ON ledger_entries(kobutsu_kind)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cls_cache_key ON classification_cache(product_key)")

        self.conn.commit()

    # === Insert/Query ===
    def insert_ledger_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        cur = self.conn.cursor()
        cols = [
            'entry_date','counterparty_type','counterparty_name','receipt_no','platform','platform_order_id','platform_user',
            'person_name','person_address','id_type','id_number','id_checked_on','id_checked_by','id_proof_ref',
            'kobutsu_kind','hinmoku','hinmei','qty','unit_price','amount','identifier','notes','correction_of'
        ]
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT INTO ledger_entries ({','.join(cols)}) VALUES ({placeholders})"
        data = [tuple(row.get(c) for c in cols) for row in rows]
        cur.executemany(sql, data)
        self.conn.commit()
        return cur.rowcount

    def query_ledger(self, where: str = "", params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        sql = (
            "SELECT *, datetime(created_at,'localtime') AS created_at_local "
            "FROM ledger_entries " + (f"WHERE {where} " if where else "") + "ORDER BY entry_date DESC, id DESC"
        )
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None



