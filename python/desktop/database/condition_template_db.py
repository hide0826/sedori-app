#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アマゾン出品コンディション説明テンプレートデータベース操作クラス

テーブル構成:
- condition_templates: テンプレート本体（1件のみ想定）
- condition_template_items: 各コンディションの説明文
"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional


class ConditionTemplateDatabase:
    """アマゾン出品コンディション説明テンプレートDB操作クラス"""

    def __init__(self, db_path: Optional[str] = None):
        """データベースの初期化"""
        if db_path is None:
            base_dir = Path(__file__).parent.parent
            db_path = str(base_dir / "data" / "hirio.db")
        
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self._ensure_db_directory()
        self._init_database()

    def _ensure_db_directory(self):
        """データベースディレクトリの存在確認"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """データベース接続を取得"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def _init_database(self):
        """データベースとテーブルの初期化"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # condition_templates テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS condition_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT 'デフォルトテンプレート',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # condition_template_items テーブル作成
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS condition_template_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                condition_key TEXT NOT NULL,
                condition_name TEXT NOT NULL,
                description TEXT,
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (template_id) REFERENCES condition_templates(id)
            )
        """)
        
        # インデックス作成
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_condition_items_template 
            ON condition_template_items(template_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_condition_items_key 
            ON condition_template_items(condition_key)
        """)
        
        conn.commit()
        
        # 初回起動時にテンプレートとデフォルト項目を作成
        self._initialize_default_template()

    def _initialize_default_template(self):
        """デフォルトテンプレートとコンディション項目を初期化"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # テンプレートが存在するか確認
        cursor.execute("SELECT id FROM condition_templates LIMIT 1")
        template_row = cursor.fetchone()
        
        if template_row is None:
            # テンプレートを作成
            cursor.execute("""
                INSERT INTO condition_templates (name)
                VALUES ('デフォルトテンプレート')
            """)
            template_id = cursor.lastrowid
            
            # デフォルトコンディション項目を作成
            default_conditions = [
                {'key': 'new', 'name': '新品', 'order': 1, 'description': ''},
                {'key': 'like_new', 'name': 'ほぼ新品', 'order': 2, 'description': ''},
                {'key': 'very_good', 'name': '非常に良い', 'order': 3, 'description': ''},
                {'key': 'good', 'name': '良い', 'order': 4, 'description': ''},
                {'key': 'acceptable', 'name': '可', 'order': 5, 'description': ''},
            ]
            
            for cond in default_conditions:
                cursor.execute("""
                    INSERT INTO condition_template_items 
                    (template_id, condition_key, condition_name, description, display_order)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    template_id,
                    cond['key'],
                    cond['name'],
                    cond['description'],
                    cond['order']
                ))
            
            conn.commit()

    def get_or_create_template(self) -> Dict[str, Any]:
        """テンプレート取得（なければ作成）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM condition_templates LIMIT 1")
        row = cursor.fetchone()
        
        if row is None:
            # テンプレートが存在しない場合は作成
            self._initialize_default_template()
            cursor.execute("SELECT * FROM condition_templates LIMIT 1")
            row = cursor.fetchone()
        
        return dict(row) if row else {}

    def save_condition_description(self, condition_key: str, condition_name: str, description: str):
        """説明文保存"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # テンプレートIDを取得
        template = self.get_or_create_template()
        template_id = template['id']
        
        # 既存の項目を確認
        cursor.execute("""
            SELECT id FROM condition_template_items
            WHERE template_id = ? AND condition_key = ?
        """, (template_id, condition_key))
        
        existing_row = cursor.fetchone()
        
        if existing_row:
            # 更新
            cursor.execute("""
                UPDATE condition_template_items
                SET condition_name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (condition_name, description, existing_row['id']))
        else:
            # 新規作成
            # display_orderを決定（既存の最大値+1）
            cursor.execute("""
                SELECT MAX(display_order) as max_order
                FROM condition_template_items
                WHERE template_id = ?
            """, (template_id,))
            max_order_row = cursor.fetchone()
            next_order = (max_order_row['max_order'] or 0) + 1 if max_order_row else 1
            
            cursor.execute("""
                INSERT INTO condition_template_items
                (template_id, condition_key, condition_name, description, display_order)
                VALUES (?, ?, ?, ?, ?)
            """, (template_id, condition_key, condition_name, description, next_order))
        
        conn.commit()

    def get_all_conditions(self) -> List[Dict[str, Any]]:
        """全コンディション取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        template = self.get_or_create_template()
        template_id = template['id']
        
        cursor.execute("""
            SELECT condition_key, condition_name, description, display_order
            FROM condition_template_items
            WHERE template_id = ?
            ORDER BY display_order ASC
        """, (template_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_condition_by_key(self, condition_key: str) -> Optional[Dict[str, Any]]:
        """キーで取得"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        template = self.get_or_create_template()
        template_id = template['id']
        
        cursor.execute("""
            SELECT condition_key, condition_name, description
            FROM condition_template_items
            WHERE template_id = ? AND condition_key = ?
        """, (template_id, condition_key))
        
        row = cursor.fetchone()
        return dict(row) if row else None

    def reset_to_default(self):
        """デフォルト値にリセット"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        template = self.get_or_create_template()
        template_id = template['id']
        
        # 既存の項目を削除
        cursor.execute("""
            DELETE FROM condition_template_items
            WHERE template_id = ?
        """, (template_id,))
        
        # デフォルト項目を作成
        default_conditions = [
            {'key': 'new', 'name': '新品', 'order': 1, 'description': ''},
            {'key': 'like_new', 'name': 'ほぼ新品', 'order': 2, 'description': ''},
            {'key': 'very_good', 'name': '非常に良い', 'order': 3, 'description': ''},
            {'key': 'good', 'name': '良い', 'order': 4, 'description': ''},
            {'key': 'acceptable', 'name': '可', 'order': 5, 'description': ''},
        ]
        
        for cond in default_conditions:
            cursor.execute("""
                INSERT INTO condition_template_items
                (template_id, condition_key, condition_name, description, display_order)
                VALUES (?, ?, ?, ?, ?)
            """, (
                template_id,
                cond['key'],
                cond['name'],
                cond['description'],
                cond['order']
            ))
        
        conn.commit()

    def close(self):
        """データベース接続を閉じる"""
        if self.conn:
            self.conn.close()
            self.conn = None

