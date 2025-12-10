#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アマゾン出品コンディション説明テンプレートデータベース操作クラス

テーブル構成:
- condition_templates: テンプレート本体（1件のみ想定）
- condition_template_items: 各コンディションの説明文
"""

import sqlite3
import json
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
                {'key': 'like_new', 'name': '中古(ほぼ新品)', 'order': 2, 'description': ''},
                {'key': 'very_good', 'name': '中古(非常に良い)', 'order': 3, 'description': ''},
                {'key': 'good', 'name': '中古(良い)', 'order': 4, 'description': ''},
                {'key': 'acceptable', 'name': '中古(可)', 'order': 5, 'description': ''},
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
            {'key': 'like_new', 'name': '中古(ほぼ新品)', 'order': 2, 'description': ''},
            {'key': 'very_good', 'name': '中古(非常に良い)', 'order': 3, 'description': ''},
            {'key': 'good', 'name': '中古(良い)', 'order': 4, 'description': ''},
            {'key': 'acceptable', 'name': '中古(可)', 'order': 5, 'description': ''},
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

    def _get_missing_keywords_path(self) -> Path:
        """欠品キーワード辞書のJSONファイルパスを取得"""
        base_dir = Path(self.db_path).parent
        return base_dir / "missing_keywords.json"
    
    def load_missing_keywords(self) -> Dict[str, Any]:
        """欠品キーワード辞書をJSONファイルから読み込み"""
        json_path = self._get_missing_keywords_path()
        
        # ファイルが存在しない場合は初期データを作成
        if not json_path.exists():
            default_data = {
                "keywords": {
                    "取説欠品": "取扱説明書が欠品しています。メーカーサイトにてダウンロード可能です。",
                    "付属ROM欠品": "付属ROMが欠品しています。",
                    "内箱欠品": "内箱なし",
                    "外箱欠品": "外箱なし"
                },
                "detection_keywords": ["欠品", "なし", "無し", "欠"]
            }
            self.save_missing_keywords(default_data)
            return default_data
        
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # 読み込みエラーの場合はデフォルトデータを返す
            default_data = {
                "keywords": {},
                "detection_keywords": ["欠品", "なし", "無し", "欠"]
            }
            return default_data
    
    def save_missing_keywords(self, keywords_dict: Dict[str, Any]):
        """欠品キーワード辞書をJSONファイルに保存"""
        json_path = self._get_missing_keywords_path()
        
        try:
            # ディレクトリが存在しない場合は作成
            json_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(keywords_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise Exception(f"欠品キーワード辞書の保存に失敗しました: {str(e)}")
    
    def get_condition_description_text(self, condition_key: str) -> str:
        """コンディションキーから説明文のテキストのみを取得"""
        condition = self.get_condition_by_key(condition_key)
        if condition and condition.get('description'):
            return condition['description']
        return ""

    def close(self):
        """データベース接続を閉じる"""
        if self.conn:
            self.conn.close()
            self.conn = None

