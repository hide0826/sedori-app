#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品データベース操作クラス

SQLite データベース `python/desktop/data/hirio.db` 内に `products` テーブルを作成し、
SKU を主キーとした商品情報の保存・更新・参照を提供する。

主な用途:
- レシート/保証書マッチング後に対象商品のレコードを更新
- 返品照合のため SKU ベースで高速検索
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class ProductDatabase:
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
        # products テーブル（SKU 主キー）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
              sku TEXT PRIMARY KEY,
              jan TEXT,
              asin TEXT,
              product_name TEXT,
              purchase_date TEXT,
              purchase_price INTEGER,
              quantity INTEGER,
              store_code TEXT,
              store_name TEXT,
              receipt_id INTEGER,
              warranty_period_days INTEGER,
              warranty_until TEXT,
              warranty_product_name TEXT,
              warranty_image_path TEXT,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 最低限のインデックス（検索高速化）
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_jan ON products(jan)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_asin ON products(asin)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_purchase_date ON products(purchase_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_store_code ON products(store_code)")

        self.conn.commit()

        # 既存 DB への後方互換: 不足カラムの追加
        def _ensure_column(table: str, column: str, coltype: str) -> None:
            try:
                cur.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cur.fetchall()]
                if column not in cols:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                    self.conn.commit()
            except Exception:
                # 失敗時は黙ってスキップ（既存環境配慮）
                pass

        for name, ctype in (
            ("warranty_period_days", "INTEGER"),
            ("warranty_until", "TEXT"),
            ("warranty_product_name", "TEXT"),
            ("warranty_image_path", "TEXT"),
            ("receipt_id", "INTEGER"),
        ):
            _ensure_column("products", name, ctype)

    # ========= 基本操作 =========
    def upsert(self, product: Dict[str, Any]) -> None:
        """SKU をキーに商品を挿入/更新する。"""
        if not product.get("sku"):
            raise ValueError("sku is required")

        # 既存判定
        exists = self.get_by_sku(product["sku"]) is not None

        fields = [
            "sku","jan","asin","product_name","purchase_date","purchase_price","quantity",
            "store_code","store_name","receipt_id","warranty_period_days","warranty_until",
            "warranty_product_name","warranty_image_path"
        ]
        values = [product.get(k) for k in fields]

        cur = self.conn.cursor()
        if exists:
            set_clause = ",".join([f"{k}=?" for k in fields if k != "sku"]) + ", updated_at=CURRENT_TIMESTAMP"
            update_values = [product.get(k) for k in fields if k != "sku"] + [product["sku"]]
            cur.execute(f"UPDATE products SET {set_clause} WHERE sku=?", update_values)
        else:
            placeholders = ",".join(["?"] * len(fields))
            cur.execute(
                f"INSERT INTO products ({','.join(fields)}) VALUES ({placeholders})",
                values,
            )
        self.conn.commit()

    def get_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM products WHERE sku = ?", (sku,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_all(self) -> List[Dict[str, Any]]:
        """全商品を更新日時の新しい順で取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM products ORDER BY IFNULL(updated_at, created_at) DESC, sku DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def list_by_date(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        where = []
        params: List[Any] = []
        if start_date:
            where.append("purchase_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("purchase_date <= ?")
            params.append(end_date)
        sql = "SELECT * FROM products"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY purchase_date DESC, sku DESC"
        cur.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def update_warranty_info(
        self,
        sku: str,
        *,
        warranty_period_days: Optional[int] = None,
        warranty_until: Optional[str] = None,
        warranty_product_name: Optional[str] = None,
        warranty_image_path: Optional[str] = None,
    ) -> bool:
        cur = self.conn.cursor()
        set_parts = []
        params: List[Any] = []
        if warranty_period_days is not None:
            set_parts.append("warranty_period_days = ?")
            params.append(warranty_period_days)
        if warranty_until is not None:
            set_parts.append("warranty_until = ?")
            params.append(warranty_until)
        if warranty_product_name is not None:
            set_parts.append("warranty_product_name = ?")
            params.append(warranty_product_name)
        if warranty_image_path is not None:
            set_parts.append("warranty_image_path = ?")
            params.append(warranty_image_path)

        if not set_parts:
            return False

        set_sql = ", ".join(set_parts) + ", updated_at=CURRENT_TIMESTAMP"
        params.append(sku)
        cur.execute(f"UPDATE products SET {set_sql} WHERE sku = ?", params)
        self.conn.commit()
        return cur.rowcount > 0

    def link_receipt(self, sku: str, receipt_id: Optional[int]) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE products SET receipt_id = ?, updated_at = CURRENT_TIMESTAMP WHERE sku = ?",
            (receipt_id, sku),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def delete(self, sku: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM products WHERE sku = ?", (sku,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


