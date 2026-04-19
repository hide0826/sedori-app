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
from PySide6.QtCore import Qt, QSettings
import sys
import os
import json

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.condition_template_db import ConditionTemplateDatabase


# コンディション定義
CONDITIONS = [
    {'key': 'new', 'name': '新品'},
    {'key': 'like_new', 'name': '中古(ほぼ新品)'},
    {'key': 'very_good', 'name': '中古(非常に良い)'},
    {'key': 'good', 'name': '中古(良い)'},
    {'key': 'acceptable', 'name': '中古(可)'},
]

MISSING_FIXED_ROWS = [
    {"key": "取説欠品", "name": "取説欠品"},
    {"key": "内箱欠品", "name": "内箱欠品"},
    {"key": "取説・内箱欠品", "name": "取説・内箱欠品"},
]
CUSTOM_TEMPLATE_KEYS = ("custom1", "custom2", "custom3")
CUSTOM_DEFAULT_LABELS = {"custom1": "カスタム1", "custom2": "カスタム2", "custom3": "カスタム3"}


class ConditionTextEdit(QWidget):
    """テーブルセル内に配置するテキストエリア"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtGui import QFont
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        # QPlainTextEditを使用（文字の重複表示を防ぐため）
        self.text_edit = QPlainTextEdit()
        self.text_edit.setMaximumHeight(100)
        # QPlainTextEditは常にプレーンテキストのみなので、setAcceptRichText()は不要
        
        # フォント設定を明示的に指定（文字の重複表示を防ぐ）
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.Normal)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
        self.text_edit.setFont(font)
        
        # テーブルセル内のウィジェットとして正しく描画されるように設定
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        
        # スタイルシートを直接設定（文字の重複表示を防ぐ）
        # 背景色はrgbaではなくrgbを使用（重複描画を防ぐ）
        # QPlainTextEdit用のスタイル
        self.text_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: rgb(60, 60, 60);
                color: rgb(255, 255, 255);
                border: 1px solid rgb(85, 85, 85);
                border-radius: 3px;
                padding: 4px 8px;
                font-family: "Segoe UI", "Meiryo", "MS Gothic", sans-serif;
                font-size: 9pt;
                font-weight: normal;
                selection-background-color: rgb(0, 120, 212);
                selection-color: rgb(255, 255, 255);
            }
            QPlainTextEdit:focus {
                border: 1px solid rgb(90, 162, 255);
                background-color: rgb(64, 64, 64);
            }
        """)
        
        # documentのスタイル設定（文字の重複表示を防ぐ）
        doc = self.text_edit.document()
        doc.setDefaultFont(font)
        # ドキュメントのマージンを0にして重複描画を防ぐ
        doc.setDocumentMargin(0)
        
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
        self.tabs.addTab(self.missing_keywords_tab, "詳細説明")
        
        layout.addWidget(self.tabs)

    @staticmethod
    def _qsettings() -> QSettings:
        """在庫・仕入まわりと同系の保存先（ユーザーごとに列幅を保持）"""
        return QSettings("HIRIO", "SedoriDesktopApp")

    def _setup_interactive_two_columns(
        self,
        table: QTableWidget,
        table_id: str,
        *,
        default_col0: int,
        default_col1: int,
    ) -> None:
        """コンディション／コメントの2列をドラッグで調整可能にし、幅を自動保存する。"""
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)

        self._restore_table_column_widths(
            table, table_id, default_col0=default_col0, default_col1=default_col1
        )

        def _on_section_resized(_logical: int, _old: int, _new: int) -> None:
            self._persist_table_column_widths(table, table_id)

        header.sectionResized.connect(_on_section_resized)

    def _table_width_settings_key(self, table_id: str) -> str:
        return f"condition_template_widget/columns/{table_id}"

    def _restore_table_column_widths(
        self,
        table: QTableWidget,
        table_id: str,
        *,
        default_col0: int,
        default_col1: int,
    ) -> None:
        s = self._qsettings()
        key = self._table_width_settings_key(table_id)
        w0 = int(s.value(f"{key}/col0", default_col0))
        w1 = int(s.value(f"{key}/col1", default_col1))
        if w0 < 60:
            w0 = default_col0
        if w1 < 100:
            w1 = default_col1
        header = table.horizontalHeader()
        header.blockSignals(True)
        try:
            table.setColumnWidth(0, w0)
            table.setColumnWidth(1, w1)
        finally:
            header.blockSignals(False)

    def _persist_table_column_widths(self, table: QTableWidget, table_id: str) -> None:
        s = self._qsettings()
        key = self._table_width_settings_key(table_id)
        s.setValue(f"{key}/col0", table.columnWidth(0))
        s.setValue(f"{key}/col1", table.columnWidth(1))
        s.sync()
    
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
        
        # ヘッダー: ユーザーが列幅を調整可能（幅は保存して復元）
        self._setup_interactive_two_columns(self.table, "condition_main", default_col0=200, default_col1=520)
        
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
        """詳細説明タブ（欠品3種＋カスタム1〜3。カスタムは名称・コメントとも自由入力）"""
        layout = QVBoxLayout(self.missing_keywords_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 説明ラベル
        info_label = QLabel(
            "よく使う欠品・詳細説明を登録できます。\n"
            "上段は名称固定、下段のカスタム1〜3は「コンディション」列の名称を自由に変えられます。"
        )
        info_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(info_label)

        # テーブル作成（コンディション説明タブと同形式）
        self.keywords_table = QTableWidget()
        self.keywords_table.setColumnCount(2)
        self.keywords_table.setHorizontalHeaderLabels(["コンディション", "コメント"])

        total_rows = len(MISSING_FIXED_ROWS) + len(CUSTOM_TEMPLATE_KEYS)
        self.keywords_table.setRowCount(total_rows)
        self.keywords_table.setAlternatingRowColors(True)
        self.keywords_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.keywords_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # ヘッダー: ユーザーが列幅を調整可能（幅は保存して復元）
        self._setup_interactive_two_columns(
            self.keywords_table, "detail_missing", default_col0=220, default_col1=500
        )

        self.missing_text_edits = {}  # キー -> ConditionTextEdit
        self.missing_label_edits = {}  # custom1〜3 -> QLineEdit

        row_i = 0
        for row_def in MISSING_FIXED_ROWS:
            name_item = QTableWidgetItem(row_def["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.keywords_table.setItem(row_i, 0, name_item)

            text_edit = ConditionTextEdit()
            self.missing_text_edits[row_def["key"]] = text_edit
            self.keywords_table.setCellWidget(row_i, 1, text_edit)
            self.keywords_table.setRowHeight(row_i, 100)
            row_i += 1

        for ck in CUSTOM_TEMPLATE_KEYS:
            label_edit = QLineEdit()
            label_edit.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label_edit.setPlaceholderText(CUSTOM_DEFAULT_LABELS[ck])
            self.missing_label_edits[ck] = label_edit
            self.keywords_table.setCellWidget(row_i, 0, label_edit)

            text_edit = ConditionTextEdit()
            self.missing_text_edits[ck] = text_edit
            self.keywords_table.setCellWidget(row_i, 1, text_edit)
            self.keywords_table.setRowHeight(row_i, 100)
            row_i += 1

        layout.addWidget(self.keywords_table)

        # ボタンエリア
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # リセットボタン
        reset_keywords_btn = QPushButton("リセット")
        reset_keywords_btn.clicked.connect(self.reset_keywords_data)
        reset_keywords_btn.setStyleSheet("""
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
        button_layout.addWidget(reset_keywords_btn)

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
            
            # 各コンディションの説明文を設定（DBでは改行を "\\n" で保存しているので表示用に実際の改行に変換）
            for condition in CONDITIONS:
                key = condition['key']
                text_edit = self.text_edits.get(key)
                if text_edit:
                    if key in db_data:
                        description = db_data[key].get('description', '') or ''
                        description = (description or "").replace("\\n", "\n")
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
        """データをデータベースに保存（改行は "\\n" で保存し、1行表示で行区切りに\\nが入る形にする）"""
        try:
            for condition in CONDITIONS:
                key = condition['key']
                name = condition['name']
                text_edit = self.text_edits.get(key)
                
                if text_edit:
                    description = text_edit.text().replace("\r\n", "\n").replace("\n", "\\n").replace("\r", "\\n")
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
        """詳細説明（欠品3＋カスタム3）を読み込んで表示"""
        try:
            keywords_data = self.condition_db.load_missing_keywords()
            keywords = keywords_data.get('keywords', {})
            custom_labels = keywords_data.get('custom_labels') or {}

            for row_def in MISSING_FIXED_ROWS:
                key = row_def["key"]
                text_edit = self.missing_text_edits.get(key)
                if text_edit:
                    text_edit.setText(str(keywords.get(key, "") or ""))

            for ck in CUSTOM_TEMPLATE_KEYS:
                le = self.missing_label_edits.get(ck)
                if le:
                    lab = custom_labels.get(ck) or CUSTOM_DEFAULT_LABELS[ck]
                    le.setText(str(lab))
                te = self.missing_text_edits.get(ck)
                if te:
                    te.setText(str(keywords.get(ck, "") or ""))
        except Exception as e:
            QMessageBox.warning(
                self,
                "読み込みエラー",
                f"詳細説明の読み込みに失敗しました:\n{str(e)}"
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
        """詳細説明を保存（欠品3＋カスタム3、カスタム表示名は custom_labels）"""
        try:
            existing_data = self.condition_db.load_missing_keywords()
            keywords = dict(existing_data.get('keywords', {}))
            detection_keywords = existing_data.get('detection_keywords', ['欠品', 'なし', '無し', '欠'])

            for row_def in MISSING_FIXED_ROWS:
                key = row_def["key"]
                text_edit = self.missing_text_edits.get(key)
                text_val = text_edit.text().strip() if text_edit else ""
                if text_val:
                    keywords[key] = text_val
                else:
                    keywords.pop(key, None)

            custom_labels: dict = {}
            for ck in CUSTOM_TEMPLATE_KEYS:
                text_edit = self.missing_text_edits.get(ck)
                text_val = text_edit.text().strip() if text_edit else ""
                if text_val:
                    keywords[ck] = text_val
                else:
                    keywords.pop(ck, None)
                le = self.missing_label_edits.get(ck)
                lab = le.text().strip() if le else ""
                if not lab:
                    lab = CUSTOM_DEFAULT_LABELS[ck]
                custom_labels[ck] = lab

            keywords_data = {
                'keywords': keywords,
                'custom_labels': custom_labels,
                'detection_keywords': detection_keywords
            }

            self.condition_db.save_missing_keywords(keywords_data)

            QMessageBox.information(
                self,
                "保存完了",
                "詳細説明を保存しました。"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "保存エラー",
                f"詳細説明の保存に失敗しました:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()

    def reset_keywords_data(self):
        """詳細説明を空欄・カスタム名をデフォルトにリセット"""
        reply = QMessageBox.question(
            self,
            "リセット確認",
            "欠品3種・カスタム3種のコメントを空欄にし、カスタムの名称を「カスタム1〜3」に戻しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        for row_def in MISSING_FIXED_ROWS:
            text_edit = self.missing_text_edits.get(row_def["key"])
            if text_edit:
                text_edit.setText("")
        for ck in CUSTOM_TEMPLATE_KEYS:
            text_edit = self.missing_text_edits.get(ck)
            if text_edit:
                text_edit.setText("")
            le = self.missing_label_edits.get(ck)
            if le:
                le.setText(CUSTOM_DEFAULT_LABELS[ck])
    
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

