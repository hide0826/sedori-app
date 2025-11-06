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

        # 学習用テーブル: キーワード→品目のマッピング（重み付き）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_category_dict (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              keyword TEXT NOT NULL,
              category TEXT NOT NULL,
              weight INTEGER DEFAULT 1,
              source TEXT DEFAULT 'user_edit',
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(keyword, category)
            )
            """
        )

        # 学習用テーブル: ID（JAN/ASIN/識別情報）→品目の直接マッピング
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_id_map (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              id_value TEXT UNIQUE NOT NULL,
              category TEXT NOT NULL,
              confidence REAL DEFAULT 1.0,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
              counterparty_branch TEXT,
              counterparty_address TEXT,
              contact TEXT,
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
              transaction_method TEXT,
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_category_dict_keyword ON ledger_category_dict(keyword)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_id_map_value ON ledger_id_map(id_value)")

        self.conn.commit()

        # 既存DBへの後方互換: 不足カラムを追加
        def _ensure_column(table: str, column: str, coltype: str) -> None:
            try:
                cur.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cur.fetchall()]
                if column not in cols:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                    self.conn.commit()
            except Exception:
                pass

        for name, ctype in (
            ("counterparty_branch", "TEXT"),
            ("counterparty_address", "TEXT"),
            ("contact", "TEXT"),
            ("transaction_method", "TEXT"),
        ):
            _ensure_column("ledger_entries", name, ctype)

    # === Insert/Query ===
    def insert_ledger_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        cur = self.conn.cursor()
        cols = [
            'entry_date','counterparty_type','counterparty_name','counterparty_branch','counterparty_address','contact','receipt_no','platform','platform_order_id','platform_user',
            'person_name','person_address','id_type','id_number','id_checked_on','id_checked_by','id_proof_ref',
            'kobutsu_kind','hinmoku','hinmei','qty','unit_price','amount','identifier','transaction_method','notes','correction_of'
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

    # === Utility (Debug) ===
    def delete_all(self) -> None:
        """Debug用途: 全データ削除（ledger_entries / purchase_rows / classification_cache）"""
        cur = self.conn.cursor()
        for tbl in ("ledger_entries", "purchase_rows", "classification_cache"):
            try:
                cur.execute(f"DELETE FROM {tbl}")
            except Exception:
                pass
        self.conn.commit()

    # === 学習機能 ===
    def learn_category_from_edit(
        self, 
        product_name: str, 
        category: str, 
        identifier: Optional[str] = None
    ) -> Dict[str, int]:
        """
        品目編集を学習する
        
        Args:
            product_name: 商品名
            category: 選択された品目
            identifier: JAN/ASIN/識別情報（オプション）
        
        Returns:
            {"keywords_added": int, "id_mapped": int} の辞書
        """
        keywords_added = 0
        id_mapped = 0
        cur = self.conn.cursor()
        
        # 1. 商品名からキーワードを抽出して学習
        keywords = self._extract_keywords(product_name)
        for keyword in keywords:
            if len(keyword) >= 2:  # 2文字以上のキーワードのみ
                # UPSERT: 既存なら重み+1、新規なら追加
                cur.execute(
                    """
                    INSERT INTO ledger_category_dict (keyword, category, weight, source, updated_at)
                    VALUES (?, ?, 1, 'user_edit', CURRENT_TIMESTAMP)
                    ON CONFLICT(keyword, category) DO UPDATE SET
                        weight = weight + 1,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (keyword, category)
                )
                keywords_added += 1
        
        # 2. 識別情報があれば直接マッピング（高信頼度）
        if identifier and identifier.strip():
            identifier = identifier.strip()
            cur.execute(
                """
                INSERT INTO ledger_id_map (id_value, category, confidence, updated_at)
                VALUES (?, ?, 1.0, CURRENT_TIMESTAMP)
                ON CONFLICT(id_value) DO UPDATE SET
                    category = ?,
                    confidence = 1.0,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (identifier, category, category)
            )
            id_mapped = 1
        
        self.conn.commit()
        return {"keywords_added": keywords_added, "id_mapped": id_mapped}
    
    def _extract_keywords(self, text: str) -> List[str]:
        """
        商品名からキーワードを抽出（正規化済み）
        
        Returns:
            キーワードのリスト
        """
        if not text:
            return []
        
        import re
        import unicodedata
        
        # 全角→半角変換
        text = unicodedata.normalize('NFKC', text)
        
        # 記号・数字のみのトークンを除去
        # 英数字・日本語・カタカナ・ひらがなを含むトークンのみ抽出
        # 2文字以上のトークンを抽出
        tokens = re.findall(r'[a-zA-Z0-9\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]{2,}', text)
        
        # 重複除去
        keywords = list(set(tokens))
        
        # 長すぎるキーワード（20文字超）は除外
        keywords = [k for k in keywords if len(k) <= 20]
        
        return keywords
    
    def match_category_by_id(self, identifier: Optional[str]) -> Optional[str]:
        """
        識別情報（JAN/ASIN）から品目を直接マッチング（高信頼度）
        
        Returns:
            品目名、見つからない場合はNone
        """
        if not identifier or not identifier.strip():
            return None
        
        cur = self.conn.cursor()
        cur.execute(
            "SELECT category FROM ledger_id_map WHERE id_value = ?",
            (identifier.strip(),)
        )
        row = cur.fetchone()
        return row['category'] if row else None
    
    def match_category_by_keywords(self, product_name: str) -> Optional[Tuple[str, int]]:
        """
        商品名のキーワードから品目を推定（重み合計で判定）
        
        Returns:
            (品目名, 重み合計) のタプル、見つからない場合はNone
        """
        if not product_name:
            return None
        
        keywords = self._extract_keywords(product_name)
        if not keywords:
            return None
        
        cur = self.conn.cursor()
        # キーワードごとに重みを合計
        placeholders = ",".join(["?"] * len(keywords))
        cur.execute(
            f"""
            SELECT category, SUM(weight) as total_weight
            FROM ledger_category_dict
            WHERE keyword IN ({placeholders})
            GROUP BY category
            ORDER BY total_weight DESC
            LIMIT 1
            """,
            keywords
        )
        row = cur.fetchone()
        if row and row['total_weight'] > 0:
            return (row['category'], row['total_weight'])
        return None



