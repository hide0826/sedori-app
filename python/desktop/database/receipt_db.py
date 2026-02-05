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
              phone_number TEXT,
              store_code TEXT,               -- 店舗マスタにマッチしたコード
              subtotal INTEGER,
              tax INTEGER,
              discount_amount INTEGER,
              total_amount INTEGER,
              paid_amount INTEGER,
              items_count INTEGER,
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

        # 既存DBの後方互換：不足カラムを追加
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
            ("phone_number", "TEXT"),
            ("items_count", "INTEGER"),
            ("original_file_path", "TEXT"),  # 元のファイルパス（リネーム用）
            ("purchase_time", "TEXT"),  # 購入時刻（HH:MM形式）
            ("sku", "TEXT"),                # 保証書連携用SKU
            ("product_name", "TEXT"),       # 保証書連携用商品名
            ("warranty_days", "INTEGER"),   # 保証期間（日数）
            ("price_difference", "INTEGER"),  # 差額（紐付けSKU合計 - レシート合計）
            ("warranty_until", "TEXT"),     # 保証終了日（yyyy-MM-dd）
            ("account_title", "TEXT"),      # レシートに紐付く勘定科目
            ("plastic_bag_amount", "INTEGER"),  # レジ袋金額（複数ある場合は合計）
            ("linked_skus", "TEXT"),        # 紐付けSKU（カンマ区切り）
            ("registration_number", "TEXT"),  # 適格請求書 登録番号 (T + 13桁)
        ):
            _ensure_column("receipts", name, ctype)

    # ==== receipts 操作 ====
    def insert_receipt(self, data: Dict[str, Any]) -> int:
        fields = [
            "file_path","purchase_date","purchase_time","store_name_raw","phone_number","store_code","subtotal","tax",
            "discount_amount","total_amount","paid_amount","items_count","currency","ocr_provider","ocr_text",
            "original_file_path","plastic_bag_amount","linked_skus","registration_number",
        ]
        placeholders = ",".join(["?"] * len(fields))
        cur = self.conn.cursor()
        cur.execute(
            f"INSERT INTO receipts ({','.join(fields)}) VALUES ({placeholders})",
            tuple(data.get(k) for k in fields),
        )
        self.conn.commit()
        return cur.lastrowid
    
    def get_file_name_from_path(self, file_path: str) -> str:
        """ファイルパスからファイル名（拡張子なし）を取得"""
        if not file_path:
            return ""
        from pathlib import Path
        return Path(file_path).stem
    
    def find_by_file_name(self, file_name: str) -> Optional[Dict[str, Any]]:
        """ファイル名でレシートを検索（画像ファイル名を識別子として使用）"""
        if not file_name:
            return None
        
        cur = self.conn.cursor()
        # ファイル名から拡張子を除去
        from pathlib import Path
        file_name_without_ext = Path(file_name).stem
        file_name_with_ext = Path(file_name).name
        
        # ファイル名を正規化（アンダースコアやハイフンの扱い）
        # 検索パターンのリスト（優先順位順）
        # ファイル名が既に拡張子なしの場合、file_name_without_extとfile_name_with_extは同じになる
        search_patterns = [
            # 1. 完全一致（ファイル名のみ、パスなし）
            file_name_without_ext,
            file_name_with_ext,
            # 2. 拡張子なしで末尾一致（最も一般的）
            f"%{file_name_without_ext}",
            # 3. 拡張子ありで末尾一致
            f"%{file_name_with_ext}",
            # 4. スラッシュ区切りで拡張子なし
            f"%/{file_name_without_ext}",
            # 5. スラッシュ区切りで拡張子あり
            f"%/{file_name_with_ext}",
            # 6. バックスラッシュ区切りで拡張子なし（Windows用）
            f"%\\{file_name_without_ext}",
            # 7. バックスラッシュ区切りで拡張子あり（Windows用）
            f"%\\{file_name_with_ext}",
            # 8. 拡張子付きで末尾一致（.jpg, .png, .jpegなど）
            f"%{file_name_without_ext}.jpg",
            f"%{file_name_without_ext}.png",
            f"%{file_name_without_ext}.jpeg",
            f"%{file_name_without_ext}.JPG",
            f"%{file_name_without_ext}.PNG",
            f"%{file_name_without_ext}.JPEG",
        ]
        
        # file_pathとoriginal_file_pathの両方を検索
        for pattern in search_patterns:
            # file_pathで検索（LIKEと=の両方を試す）
            if '%' not in pattern:
                # 完全一致
                cur.execute("SELECT * FROM receipts WHERE file_path = ? OR file_path LIKE ?", (pattern, f"%{pattern}"))
            else:
                cur.execute("SELECT * FROM receipts WHERE file_path LIKE ?", (pattern,))
            row = cur.fetchone()
            if row:
                return dict(row)
            
            # original_file_pathで検索
            if '%' not in pattern:
                # 完全一致
                cur.execute("SELECT * FROM receipts WHERE original_file_path = ? OR original_file_path LIKE ?", (pattern, f"%{pattern}"))
            else:
                cur.execute("SELECT * FROM receipts WHERE original_file_path LIKE ?", (pattern,))
            row = cur.fetchone()
            if row:
                return dict(row)
        
        return None

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
    
    def delete_receipt(self, receipt_id: int) -> bool:
        """レシートを削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_receipt(self, receipt_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def find_by_date_and_store(self, purchase_date: Optional[str], store_code: Optional[str] = None) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        if purchase_date:
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
        elif store_code:
            cur.execute(
                "SELECT * FROM receipts WHERE store_code = ? ORDER BY id DESC",
                (store_code,),
            )
        else:
            cur.execute(
                "SELECT * FROM receipts ORDER BY id DESC",
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

    # ==== 削除系 ====
    def delete_receipt_by_id(self, receipt_id: int) -> bool:
        """IDを指定してレシートを削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def delete_all_receipts(self) -> int:
        """レシートを全削除（テスト用）"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM receipts")
        deleted = cur.rowcount
        self.conn.commit()
        return deleted or 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


