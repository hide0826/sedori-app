#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仕入履歴データベース操作クラス

SQLite データベース `python/desktop/data/hirio.db` 内に `purchases` テーブルを作成し、
仕入情報の保存・更新・参照を提供する。

主な用途:
- 仕入情報の管理（いつ・どこで・いくらで買ったか）
- 商品マスタ(products)への参照
- 古物台帳情報の統合管理
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class PurchaseDatabase:
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
        
        # purchases テーブル（仕入履歴）
        # 古物台帳カラムを追加
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS purchases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              product_id INTEGER,
              sku TEXT UNIQUE NOT NULL,
              purchase_date TEXT,
              purchase_price INTEGER,
              quantity INTEGER DEFAULT 1,
              store_code TEXT,
              store_name TEXT,
              condition_code INTEGER,
              condition_note TEXT,
              receipt_id INTEGER,
              comment TEXT,
              other_cost INTEGER DEFAULT 0,
              
              /* 古物台帳用カラム */
              kobutsu_kind TEXT,
              hinmoku TEXT,
              hinmei TEXT,
              person_name TEXT,
              id_type TEXT,
              id_number TEXT,
              id_checked_on TEXT,
              id_checked_by TEXT,
              ledger_registered INTEGER DEFAULT 0,
              
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (product_id) REFERENCES products(id)
            )
            """
        )

        # インデックス作成
        cur.execute("CREATE INDEX IF NOT EXISTS idx_purchases_sku ON purchases(sku)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_purchases_purchase_date ON purchases(purchase_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_purchases_store_code ON purchases(store_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_purchases_product_id ON purchases(product_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_purchases_ledger_registered ON purchases(ledger_registered)")

        self.conn.commit()

        # 既存DBへのカラム追加（マイグレーション）
        self._migrate_columns(cur)

    def _migrate_columns(self, cur: sqlite3.Cursor) -> None:
        """不足しているカラムを追加する"""
        # テーブル情報を取得
        cur.execute("PRAGMA table_info(purchases)")
        existing_cols = {row["name"] for row in cur.fetchall()}

        # 追加すべきカラム定義 (name, type)
        new_columns = [
            ("kobutsu_kind", "TEXT"),
            ("hinmoku", "TEXT"),
            ("hinmei", "TEXT"),
            ("person_name", "TEXT"),
            ("id_type", "TEXT"),
            ("id_number", "TEXT"),
            ("id_checked_on", "TEXT"),
            ("id_checked_by", "TEXT"),
            ("ledger_registered", "INTEGER DEFAULT 0"),
            # 画像カラム（Amazon Lファイル用）
            ("image_url_1", "TEXT"),
            ("image_url_2", "TEXT"),
            ("image_url_3", "TEXT"),
            ("image_url_4", "TEXT"),
            ("image_url_5", "TEXT"),
            ("barcode_image_url", "TEXT"),  # バーコード画像用（識別用、Amazon Lファイルには使用しない）
            # 利益率とROI
            ("expected_margin", "REAL"),  # 想定利益率（%）
            ("expected_roi", "REAL"),     # 想定ROI（%）
        ]

        for col_name, col_def in new_columns:
            if col_name not in existing_cols:
                try:
                    cur.execute(f"ALTER TABLE purchases ADD COLUMN {col_name} {col_def}")
                    # print(f"Added column {col_name} to purchases table")
                except Exception as e:
                    print(f"Error adding column {col_name}: {e}")
        
        self.conn.commit()

    # ========= 基本操作 =========
    def upsert(self, purchase: Dict[str, Any]) -> int:
        """
        仕入情報を挿入/更新する
        
        Args:
            purchase: 仕入情報の辞書
        
        Returns:
            挿入/更新されたレコードのID
        """
        if not purchase.get("sku"):
            raise ValueError("sku is required")

        # 既存判定
        existing = self.get_by_sku(purchase["sku"])

        fields = [
            "product_id", "sku", "purchase_date", "purchase_price", "quantity",
            "store_code", "store_name", "condition_code", "condition_note",
            "receipt_id", "comment", "other_cost", "expected_margin", "expected_roi"
        ]
        # purchase辞書に含まれるキーのみを対象とする（古物台帳カラムも更新対象に含めるか検討）
        # ここでは基本的な仕入情報の更新のみ行う
        
        # 画像カラムが含まれている場合は追加
        image_fields = [
            "image_url_1", "image_url_2", "image_url_3", "image_url_4", "image_url_5",
            "barcode_image_url"
        ]
        for img_field in image_fields:
            if img_field in purchase:
                fields.append(img_field)
        
        values = [purchase.get(k) for k in fields]

        cur = self.conn.cursor()
        if existing:
            # 更新
            set_clause = ",".join([f"{k}=?" for k in fields if k != "sku"]) + ", updated_at=CURRENT_TIMESTAMP"
            update_values = [purchase.get(k) for k in fields if k != "sku"] + [purchase["sku"]]
            cur.execute(f"UPDATE purchases SET {set_clause} WHERE sku=?", update_values)
            purchase_id = existing["id"]
        else:
            # 挿入
            placeholders = ",".join(["?"] * len(fields))
            cur.execute(
                f"INSERT INTO purchases ({','.join(fields)}) VALUES ({placeholders})",
                values,
            )
            purchase_id = cur.lastrowid
        
        self.conn.commit()
        return purchase_id

    def update_ledger_info(self, sku: str, ledger_info: Dict[str, Any]) -> bool:
        """
        古物台帳情報を更新する
        
        Args:
            sku: SKU
            ledger_info: 古物台帳情報の辞書
                kobutsu_kind, hinmoku, hinmei, person_name, 
                id_type, id_number, id_checked_on, id_checked_by
        
        Returns:
            更新成功ならTrue
        """
        if not sku:
            return False
            
        cur = self.conn.cursor()
        
        # 更新対象のカラム
        target_cols = [
            "kobutsu_kind", "hinmoku", "hinmei",
            "person_name", "id_type", "id_number",
            "id_checked_on", "id_checked_by"
        ]
        
        # 値の準備
        update_cols = []
        values = []
        
        for col in target_cols:
            if col in ledger_info:
                update_cols.append(f"{col}=?")
                values.append(ledger_info[col])
        
        if not update_cols:
            return False
            
        # 登録済みフラグを立てる
        update_cols.append("ledger_registered=1")
        update_cols.append("updated_at=CURRENT_TIMESTAMP")
        
        values.append(sku)
        
        sql = f"UPDATE purchases SET {', '.join(update_cols)} WHERE sku=?"
        
        try:
            cur.execute(sql, values)
            self.conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"Error updating ledger info for SKU {sku}: {e}")
            return False

    def get_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """SKUで仕入情報を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM purchases WHERE sku = ?", (sku,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_id(self, purchase_id: int) -> Optional[Dict[str, Any]]:
        """IDで仕入情報を取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM purchases WHERE id = ?", (purchase_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        """全仕入情報を取得（更新日時の新しい順）"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM purchases ORDER BY IFNULL(updated_at, created_at) DESC, sku DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_date(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """期間で仕入情報を取得"""
        cur = self.conn.cursor()
        where = []
        params: List[Any] = []
        if start_date:
            where.append("purchase_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("purchase_date <= ?")
            params.append(end_date)
        sql = "SELECT * FROM purchases"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY purchase_date DESC, sku DESC"
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def list_by_store(self, store_code: str) -> List[Dict[str, Any]]:
        """店舗コードで仕入情報を取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM purchases WHERE store_code = ? ORDER BY purchase_date DESC",
            (store_code,)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_ledger_registered(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """古物台帳登録済みのデータを取得"""
        cur = self.conn.cursor()
        where = ["ledger_registered = 1"]
        params: List[Any] = []
        
        if start_date:
            where.append("purchase_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("purchase_date <= ?")
            params.append(end_date)
            
        sql = "SELECT * FROM purchases WHERE " + " AND ".join(where) + " ORDER BY purchase_date DESC, sku DESC"
        
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def delete(self, sku: str) -> bool:
        """SKUで仕入情報を削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM purchases WHERE sku = ?", (sku,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None
