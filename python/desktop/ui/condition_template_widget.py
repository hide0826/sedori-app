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

try:
    from utils.ensure_desktop_sys_path import ensure_desktop_on_sys_path
except ImportError:
    from desktop.utils.ensure_desktop_sys_path import ensure_desktop_on_sys_path  # type: ignore
ensure_desktop_on_sys_path()

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

try:
    from ui.inventory.support import (
        default_custom_template_label,
        is_custom_template_key,
        list_custom_template_keys,
        next_custom_template_key,
    )
except ImportError:
    from desktop.ui.inventory.support import (  # type: ignore
        default_custom_template_label,
        is_custom_template_key,
        list_custom_template_keys,
        next_custom_template_key,
    )


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
        """詳細説明タブ（欠品3種＋カスタム無制限。カスタムは名称・コメントとも自由入力）"""
        layout = QVBoxLayout(self.missing_keywords_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        info_label = QLabel(
            "よく使う欠品・詳細説明を登録できます。\n"
            "上段3行は名称固定。下段のカスタムは名称を自由に変えられ、"
            "「行を追加」で何件でも増やせます。"
        )
        info_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(info_label)

        self.keywords_table = QTableWidget()
        self.keywords_table.setColumnCount(2)
        self.keywords_table.setHorizontalHeaderLabels(["コンディション", "コメント"])
        self.keywords_table.setAlternatingRowColors(True)
        self.keywords_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.keywords_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._setup_interactive_two_columns(
            self.keywords_table, "detail_missing", default_col0=220, default_col1=500
        )

        self.missing_text_edits = {}  # キー -> ConditionTextEdit
        self.missing_label_edits = {}  # customN -> QLineEdit
        self._custom_row_keys: list[str] = []

        self.keywords_table.setRowCount(len(MISSING_FIXED_ROWS))
        for row_i, row_def in enumerate(MISSING_FIXED_ROWS):
            name_item = QTableWidgetItem(row_def["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self.keywords_table.setItem(row_i, 0, name_item)

            text_edit = ConditionTextEdit()
            self.missing_text_edits[row_def["key"]] = text_edit
            self.keywords_table.setCellWidget(row_i, 1, text_edit)
            self.keywords_table.setRowHeight(row_i, 100)

        layout.addWidget(self.keywords_table)

        button_layout = QHBoxLayout()
        add_row_btn = QPushButton("行を追加")
        add_row_btn.setToolTip("カスタム詳細説明を1行追加します（件数に上限はありません）。")
        add_row_btn.clicked.connect(self.add_keyword_row)
        add_row_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
        """)
        button_layout.addWidget(add_row_btn)

        delete_row_btn = QPushButton("選択行を削除")
        delete_row_btn.setToolTip("選択したカスタム行を削除します（上段の欠品3種は削除できません）。")
        delete_row_btn.clicked.connect(self.delete_keyword_row)
        delete_row_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #616161;
            }
        """)
        button_layout.addWidget(delete_row_btn)
        button_layout.addStretch()

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
        self.load_keywords_data()

    def _append_custom_row(self, key: str, *, label: str = "", comment: str = "") -> None:
        """カスタム行をテーブル末尾に追加する。"""
        row_i = self.keywords_table.rowCount()
        self.keywords_table.insertRow(row_i)

        label_edit = QLineEdit()
        label_edit.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        placeholder = default_custom_template_label(key)
        label_edit.setPlaceholderText(placeholder)
        label_edit.setText(label or placeholder)
        self.missing_label_edits[key] = label_edit
        self.keywords_table.setCellWidget(row_i, 0, label_edit)

        text_edit = ConditionTextEdit()
        text_edit.setText(comment or "")
        self.missing_text_edits[key] = text_edit
        self.keywords_table.setCellWidget(row_i, 1, text_edit)
        self.keywords_table.setRowHeight(row_i, 100)
        self._custom_row_keys.append(key)

    def _clear_custom_rows(self) -> None:
        """カスタム行だけをテーブルから外す（欠品3種は残す）。"""
        while self.keywords_table.rowCount() > len(MISSING_FIXED_ROWS):
            row = self.keywords_table.rowCount() - 1
            self.keywords_table.removeRow(row)
        for key in list(self._custom_row_keys):
            self.missing_text_edits.pop(key, None)
            self.missing_label_edits.pop(key, None)
        self._custom_row_keys = []
    
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
        """詳細説明（欠品3＋カスタムN）を読み込んで表示"""
        try:
            keywords_data = self.condition_db.load_missing_keywords()
            keywords = keywords_data.get('keywords', {}) or {}
            custom_labels = keywords_data.get('custom_labels') or {}

            for row_def in MISSING_FIXED_ROWS:
                key = row_def["key"]
                text_edit = self.missing_text_edits.get(key)
                if text_edit:
                    text_edit.setText(str(keywords.get(key, "") or ""))

            self._clear_custom_rows()
            for ck in list_custom_template_keys(keywords_data, ensure_defaults=True):
                lab = str(custom_labels.get(ck) or default_custom_template_label(ck))
                comment = str(keywords.get(ck, "") or "")
                self._append_custom_row(ck, label=lab, comment=comment)
        except Exception as e:
            QMessageBox.warning(
                self,
                "読み込みエラー",
                f"詳細説明の読み込みに失敗しました:\n{str(e)}"
            )

    def add_keyword_row(self):
        """カスタム詳細説明を1行追加（件数上限なし）"""
        key = next_custom_template_key(self._custom_row_keys)
        self._append_custom_row(key)
        self.keywords_table.setCurrentCell(self.keywords_table.rowCount() - 1, 0)
        le = self.missing_label_edits.get(key)
        if le:
            le.setFocus()
            le.selectAll()

    def delete_keyword_row(self):
        """選択したカスタム行を削除（欠品3種は不可）"""
        current_row = self.keywords_table.currentRow()
        fixed_count = len(MISSING_FIXED_ROWS)
        if current_row < 0:
            QMessageBox.information(
                self,
                "削除",
                "削除するカスタム行を選択してください。",
            )
            return
        if current_row < fixed_count:
            QMessageBox.information(
                self,
                "削除",
                "上段の欠品3種（取説／内箱／取説・内箱）は削除できません。\n"
                "カスタム行を選んでください。",
            )
            return

        reply = QMessageBox.question(
            self,
            "削除確認",
            "選択したカスタム行を削除しますか？\n（保存するまでファイルには反映されません）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        custom_index = current_row - fixed_count
        if custom_index < 0 or custom_index >= len(self._custom_row_keys):
            return
        key = self._custom_row_keys.pop(custom_index)
        self.missing_text_edits.pop(key, None)
        self.missing_label_edits.pop(key, None)
        self.keywords_table.removeRow(current_row)

    def save_keywords_data(self):
        """詳細説明を保存（欠品3＋カスタムN、カスタム表示名は custom_labels）"""
        try:
            existing_data = self.condition_db.load_missing_keywords()
            keywords = dict(existing_data.get('keywords', {}) or {})
            detection_keywords = existing_data.get(
                'detection_keywords', ['欠品', 'なし', '無し', '欠']
            )

            # 旧カスタムキーをいったん除去し、画面上の行だけ残す
            for old_key in list(keywords.keys()):
                if is_custom_template_key(old_key):
                    keywords.pop(old_key, None)

            for row_def in MISSING_FIXED_ROWS:
                key = row_def["key"]
                text_edit = self.missing_text_edits.get(key)
                text_val = text_edit.text().strip() if text_edit else ""
                if text_val:
                    keywords[key] = text_val
                else:
                    keywords.pop(key, None)

            custom_labels: dict = {}
            for ck in list(self._custom_row_keys):
                text_edit = self.missing_text_edits.get(ck)
                text_val = text_edit.text().strip() if text_edit else ""
                if text_val:
                    keywords[ck] = text_val
                le = self.missing_label_edits.get(ck)
                lab = le.text().strip() if le else ""
                if not lab:
                    lab = default_custom_template_label(ck)
                custom_labels[ck] = lab

            keywords_data = {
                'keywords': keywords,
                'custom_labels': custom_labels,
                'detection_keywords': detection_keywords,
            }
            self.condition_db.save_missing_keywords(keywords_data)

            QMessageBox.information(
                self,
                "保存完了",
                "詳細説明を保存しました。",
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
        """詳細説明を空欄にし、カスタムを初期の3行に戻す"""
        reply = QMessageBox.question(
            self,
            "リセット確認",
            "欠品3種のコメントを空欄にし、カスタム行を「カスタム1〜3」の空欄3行に戻しますか？\n"
            "（保存するまでファイルには反映されません）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for row_def in MISSING_FIXED_ROWS:
            text_edit = self.missing_text_edits.get(row_def["key"])
            if text_edit:
                text_edit.setText("")

        self._clear_custom_rows()
        for i in range(1, 4):
            key = f"custom{i}"
            self._append_custom_row(key, label=default_custom_template_label(key), comment="")
    
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

