#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アマゾン出品コンディション説明設定ウィジェット
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView
)
from PySide6.QtCore import Qt
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.condition_template_db import ConditionTemplateDatabase


# コンディション定義
CONDITIONS = [
    {'key': 'new', 'name': '新品'},
    {'key': 'like_new', 'name': 'ほぼ新品'},
    {'key': 'very_good', 'name': '非常に良い'},
    {'key': 'good', 'name': '良い'},
    {'key': 'acceptable', 'name': '可'},
]


class ConditionTextEdit(QWidget):
    """テーブルセル内に配置するテキストエリア"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTextEdit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.text_edit = QTextEdit()
        self.text_edit.setMaximumHeight(100)
        self.text_edit.setAcceptRichText(False)
        layout.addWidget(self.text_edit)
    
    def setText(self, text: str):
        self.text_edit.setPlainText(text)
    
    def text(self) -> str:
        return self.text_edit.toPlainText()


class ConditionTemplateWidget(QWidget):
    """アマゾン出品コンディション説明設定ウィジェット"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.condition_db = ConditionTemplateDatabase()
        self.text_edits = {}  # condition_key -> ConditionTextEdit
        
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # テーブル作成
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["コンディション", "コメント"])
        
        # テーブル設定
        self.table.setRowCount(len(CONDITIONS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        # ヘッダー設定
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        
        # 各行にコンディションとテキストエリアを配置
        for i, condition in enumerate(CONDITIONS):
            # コンディション名（編集不可）
            name_item = QTableWidgetItem(condition['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.table.setItem(i, 0, name_item)
            
            # 説明文（テキストエリア）
            text_edit = ConditionTextEdit()
            self.text_edits[condition['key']] = text_edit
            self.table.setCellWidget(i, 1, text_edit)
            
            # 行の高さを調整
            self.table.setRowHeight(i, 100)
        
        layout.addWidget(self.table)
        
        # ボタンエリア
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # リセットボタン
        reset_btn = QPushButton("リセット")
        reset_btn.clicked.connect(self.reset_to_default)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        button_layout.addWidget(reset_btn)
        
        # 保存ボタン
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_data)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    def load_data(self):
        """データベースからデータを読み込んで表示"""
        try:
            conditions = self.condition_db.get_all_conditions()
            
            # データベースのデータを辞書に変換
            db_data = {cond['condition_key']: cond for cond in conditions}
            
            # 各コンディションの説明文を設定
            for condition in CONDITIONS:
                key = condition['key']
                text_edit = self.text_edits.get(key)
                if text_edit:
                    if key in db_data:
                        description = db_data[key].get('description', '') or ''
                        text_edit.setText(description)
                    else:
                        text_edit.setText('')
        except Exception as e:
            QMessageBox.warning(
                self,
                "読み込みエラー",
                f"データの読み込みに失敗しました:\n{str(e)}"
            )
    
    def save_data(self):
        """データをデータベースに保存"""
        try:
            for condition in CONDITIONS:
                key = condition['key']
                name = condition['name']
                text_edit = self.text_edits.get(key)
                
                if text_edit:
                    description = text_edit.text()
                    self.condition_db.save_condition_description(key, name, description)
            
            QMessageBox.information(
                self,
                "保存完了",
                "コンディション説明を保存しました。"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "保存エラー",
                f"データの保存に失敗しました:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
    
    def reset_to_default(self):
        """デフォルト値にリセット"""
        reply = QMessageBox.question(
            self,
            "リセット確認",
            "すべての説明文を空欄にリセットしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.condition_db.reset_to_default()
                self.load_data()
                QMessageBox.information(
                    self,
                    "リセット完了",
                    "デフォルト値にリセットしました。"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "リセットエラー",
                    f"リセットに失敗しました:\n{str(e)}"
                )

