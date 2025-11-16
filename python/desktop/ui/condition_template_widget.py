#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アマゾン出品コンディション説明設定ウィジェット
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
    QTabWidget, QLabel, QLineEdit, QFileDialog
)
from PySide6.QtCore import Qt
import sys
import os
import json

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
        
        # サブタブ
        self.tabs = QTabWidget()
        
        # タブ1: コンディション説明
        self.condition_tab = QWidget()
        self._setup_condition_tab()
        self.tabs.addTab(self.condition_tab, "コンディション説明")
        
        # タブ2: 欠品キーワード辞書
        self.missing_keywords_tab = QWidget()
        self._setup_missing_keywords_tab()
        self.tabs.addTab(self.missing_keywords_tab, "欠品キーワード辞書")
        
        layout.addWidget(self.tabs)
    
    def _setup_condition_tab(self):
        """コンディション説明タブの設定"""
        layout = QVBoxLayout(self.condition_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # プレースホルダーの説明
        hint_label = QLabel(
            "欠品情報を挿入したい位置に `{欠品}` と入力してください。\n"
            "欠品情報がない場合は自動的に削除されます。"
        )
        hint_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(hint_label)
        
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
    
    def _setup_missing_keywords_tab(self):
        """欠品キーワード辞書タブの設定"""
        layout = QVBoxLayout(self.missing_keywords_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 説明ラベル
        info_label = QLabel(
            "よくある欠品情報のキーワードと変換後の文章を設定できます。\n"
            "辞書にないキーワードは「【欠品情報】」見出しのみが挿入されます。"
        )
        info_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(info_label)
        
        # テーブル作成
        self.keywords_table = QTableWidget()
        self.keywords_table.setColumnCount(2)
        self.keywords_table.setHorizontalHeaderLabels(["キーワード", "変換後の文章"])
        
        # テーブル設定
        self.keywords_table.setAlternatingRowColors(True)
        self.keywords_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.keywords_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked)
        
        # ヘッダー設定
        header = self.keywords_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        
        layout.addWidget(self.keywords_table)
        
        # ボタンエリア
        button_layout = QHBoxLayout()
        
        # 追加ボタン
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_keyword_row)
        button_layout.addWidget(add_btn)
        
        # 削除ボタン
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_keyword_row)
        button_layout.addWidget(delete_btn)
        
        button_layout.addStretch()
        
        # インポートボタン
        import_btn = QPushButton("インポート")
        import_btn.clicked.connect(self.import_keywords)
        button_layout.addWidget(import_btn)
        
        # エクスポートボタン
        export_btn = QPushButton("エクスポート")
        export_btn.clicked.connect(self.export_keywords)
        button_layout.addWidget(export_btn)
        
        # 保存ボタン
        save_keywords_btn = QPushButton("保存")
        save_keywords_btn.clicked.connect(self.save_keywords_data)
        save_keywords_btn.setStyleSheet("""
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
        button_layout.addWidget(save_keywords_btn)
        
        layout.addLayout(button_layout)
        
        # データを読み込んで表示
        self.load_keywords_data()
    
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
    
    def load_keywords_data(self):
        """欠品キーワード辞書を読み込んで表示"""
        try:
            keywords_data = self.condition_db.load_missing_keywords()
            keywords = keywords_data.get('keywords', {})
            
            # テーブルに行を追加
            self.keywords_table.setRowCount(len(keywords))
            
            row = 0
            for keyword, converted_text in keywords.items():
                # キーワード
                keyword_item = QTableWidgetItem(keyword)
                self.keywords_table.setItem(row, 0, keyword_item)
                
                # 変換後の文章
                converted_item = QTableWidgetItem(converted_text)
                self.keywords_table.setItem(row, 1, converted_item)
                
                row += 1
        except Exception as e:
            QMessageBox.warning(
                self,
                "読み込みエラー",
                f"欠品キーワード辞書の読み込みに失敗しました:\n{str(e)}"
            )
    
    def add_keyword_row(self):
        """新しいキーワード行を追加"""
        row_count = self.keywords_table.rowCount()
        self.keywords_table.insertRow(row_count)
        
        # 空のアイテムを追加
        keyword_item = QTableWidgetItem("")
        converted_item = QTableWidgetItem("")
        self.keywords_table.setItem(row_count, 0, keyword_item)
        self.keywords_table.setItem(row_count, 1, converted_item)
        
        # 編集モードにする
        self.keywords_table.editItem(keyword_item)
    
    def delete_keyword_row(self):
        """選択されたキーワード行を削除"""
        current_row = self.keywords_table.currentRow()
        if current_row < 0:
            QMessageBox.information(
                self,
                "削除",
                "削除する行を選択してください。"
            )
            return
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            "選択した行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.keywords_table.removeRow(current_row)
    
    def save_keywords_data(self):
        """欠品キーワード辞書を保存"""
        try:
            keywords = {}
            
            # テーブルからデータを取得
            for row in range(self.keywords_table.rowCount()):
                keyword_item = self.keywords_table.item(row, 0)
                converted_item = self.keywords_table.item(row, 1)
                
                if keyword_item and converted_item:
                    keyword = keyword_item.text().strip()
                    converted_text = converted_item.text().strip()
                    
                    if keyword:  # キーワードが空でない場合のみ追加
                        keywords[keyword] = converted_text
            
            # 既存のデータを読み込んでdetection_keywordsを保持
            existing_data = self.condition_db.load_missing_keywords()
            detection_keywords = existing_data.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])
            
            # 保存
            keywords_data = {
                'keywords': keywords,
                'detection_keywords': detection_keywords
            }
            
            self.condition_db.save_missing_keywords(keywords_data)
            
            QMessageBox.information(
                self,
                "保存完了",
                "欠品キーワード辞書を保存しました。"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "保存エラー",
                f"欠品キーワード辞書の保存に失敗しました:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
    
    def import_keywords(self):
        """欠品キーワード辞書をインポート"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "欠品キーワード辞書をインポート",
            "",
            "JSONファイル (*.json)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)
            
            # データ形式を確認
            if 'keywords' not in imported_data:
                QMessageBox.warning(
                    self,
                    "インポートエラー",
                    "不正なファイル形式です。"
                )
                return
            
            # テーブルに反映
            keywords = imported_data.get('keywords', {})
            self.keywords_table.setRowCount(len(keywords))
            
            row = 0
            for keyword, converted_text in keywords.items():
                keyword_item = QTableWidgetItem(keyword)
                converted_item = QTableWidgetItem(converted_text)
                self.keywords_table.setItem(row, 0, keyword_item)
                self.keywords_table.setItem(row, 1, converted_item)
                row += 1
            
            QMessageBox.information(
                self,
                "インポート完了",
                "欠品キーワード辞書をインポートしました。\n保存ボタンを押して保存してください。"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "インポートエラー",
                f"インポートに失敗しました:\n{str(e)}"
            )
    
    def export_keywords(self):
        """欠品キーワード辞書をエクスポート"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "欠品キーワード辞書をエクスポート",
            "missing_keywords.json",
            "JSONファイル (*.json)"
        )
        
        if not file_path:
            return
        
        try:
            # テーブルからデータを取得
            keywords = {}
            for row in range(self.keywords_table.rowCount()):
                keyword_item = self.keywords_table.item(row, 0)
                converted_item = self.keywords_table.item(row, 1)
                
                if keyword_item and converted_item:
                    keyword = keyword_item.text().strip()
                    converted_text = converted_item.text().strip()
                    
                    if keyword:
                        keywords[keyword] = converted_text
            
            # 既存のデータを読み込んでdetection_keywordsを保持
            existing_data = self.condition_db.load_missing_keywords()
            detection_keywords = existing_data.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])
            
            # エクスポート
            export_data = {
                'keywords': keywords,
                'detection_keywords': detection_keywords
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(
                self,
                "エクスポート完了",
                f"欠品キーワード辞書をエクスポートしました。\n{file_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "エクスポートエラー",
                f"エクスポートに失敗しました:\n{str(e)}"
            )

