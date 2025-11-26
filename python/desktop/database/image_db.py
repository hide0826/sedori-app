#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像データベース操作クラス

SQLite データベース `python/desktop/data/hirio.db` 内に `product_images` テーブルを作成し、
画像ファイルのメタデータ（JAN、撮影時刻、回転角度など）を保存・更新・参照する。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class ImageDatabase:
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
        # product_images テーブル
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS product_images (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              jan TEXT,
              group_index INTEGER,
              file_path TEXT UNIQUE,
              capture_time TEXT,
              rotation INTEGER DEFAULT 0,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # インデックス（検索高速化）
        cur.execute("CREATE INDEX IF NOT EXISTS idx_product_images_jan ON product_images(jan)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_product_images_file_path ON product_images(file_path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_product_images_capture_time ON product_images(capture_time)")

        self.conn.commit()

    # ========= 基本操作 =========
    def upsert(self, image_record: Dict[str, Any]) -> int:
        """
        画像レコードを挿入/更新する
        
        Args:
            image_record: 画像レコード辞書
                - file_path: ファイルパス（必須）
                - jan: JANコード（オプション）
                - group_index: グループインデックス（オプション）
                - capture_time: 撮影時刻（オプション）
                - rotation: 回転角度（オプション、デフォルト0）
        
        Returns:
            レコードID
        """
        file_path = image_record.get("file_path")
        if not file_path:
            raise ValueError("file_path is required")

        # 既存判定
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM product_images WHERE file_path = ?", (file_path,))
        existing = cur.fetchone()

        fields = ["jan", "group_index", "file_path", "capture_time", "rotation"]
        values = [image_record.get(k) for k in fields]

        if existing:
            # 更新
            set_clause = ",".join([f"{k}=?" for k in fields if k != "file_path"]) + ", updated_at=CURRENT_TIMESTAMP"
            update_values = [image_record.get(k) for k in fields if k != "file_path"] + [file_path]
            cur.execute(f"UPDATE product_images SET {set_clause} WHERE file_path=?", update_values)
            self.conn.commit()
            return existing["id"]
        else:
            # 新規挿入
            placeholders = ",".join(["?"] * len(fields))
            cur.execute(
                f"INSERT INTO product_images ({','.join(fields)}) VALUES ({placeholders})",
                values,
            )
            self.conn.commit()
            return cur.lastrowid

    def get_by_file_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        """ファイルパスで画像レコードを取得"""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM product_images WHERE file_path = ?", (file_path,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_jan(self, jan: str) -> List[Dict[str, Any]]:
        """JANコードで画像レコードを取得"""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM product_images WHERE jan = ? ORDER BY capture_time ASC, id ASC",
            (jan,)
        )
        return [dict(r) for r in cur.fetchall()]

    def update_rotation(self, file_path: str, rotation: int) -> bool:
        """回転角度を更新"""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE product_images SET rotation = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
            (rotation, file_path)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_jan(self, file_path: str, jan: str) -> bool:
        """JANコードを更新"""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE product_images SET jan = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
            (jan, file_path)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_all(self, order_by: str = "capture_time ASC") -> List[Dict[str, Any]]:
        """全画像レコードを取得"""
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM product_images ORDER BY {order_by}")
        return [dict(r) for r in cur.fetchall()]

    def delete_by_file_path(self, file_path: str) -> bool:
        """ファイルパスで画像レコードを削除"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM product_images WHERE file_path = ?", (file_path,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None




