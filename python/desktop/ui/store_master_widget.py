#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
店舗マスタ管理ウィジェット

店舗マスタの追加・編集・削除機能
- Excelインポート機能
- カスタムフィールド対応
- 検索・フィルタ機能
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QFileDialog, QTextEdit,
    QComboBox, QCheckBox, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from typing import Tuple
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from database.store_db import StoreDatabase
from utils.excel_importer import ExcelImporter


class StoreEditDialog(QDialog):
    """店舗編集ダイアログ"""
    
    def __init__(self, parent=None, store_data=None, custom_fields_def=None):
        super().__init__(parent)
        self.store_data = store_data
        self.custom_fields_def = custom_fields_def or []
        self.db = StoreDatabase()
        
        self.setWindowTitle("店舗編集" if store_data else "店舗追加")
        self.setModal(True)
        self.setup_ui()
        
        if store_data:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        # 基本情報フォーム
        form_group = QGroupBox("基本情報")
        form_layout = QFormLayout(form_group)
        
        # 所属ルート名: 編集可能なQComboBox
        self.affiliated_route_name_combo = QComboBox()
        self.affiliated_route_name_combo.setEditable(True)  # 編集可能に設定
        self.affiliated_route_name_combo.setInsertPolicy(QComboBox.NoInsert)  # 新規入力時は追加しない
        # 既存ルート名一覧をロード
        self.load_route_names()
        # ルート選択変更時のシグナル接続
        self.affiliated_route_name_combo.currentTextChanged.connect(self.on_route_name_changed)
        # 編集時のシグナル接続（テキスト入力時）
        self.affiliated_route_name_combo.lineEdit().textChanged.connect(self.on_route_name_text_changed)
        form_layout.addRow("所属ルート名:", self.affiliated_route_name_combo)
        
        self.route_code_edit = QLineEdit()
        self.route_code_edit.setReadOnly(True)  # 自動挿入なので読み取り専用
        form_layout.addRow("ルートコード:", self.route_code_edit)
        
        self.supplier_code_edit = QLineEdit()
        form_layout.addRow("仕入れ先コード:", self.supplier_code_edit)
        
        self.store_name_edit = QLineEdit()
        self.store_name_edit.setPlaceholderText("必須項目")
        form_layout.addRow("店舗名:", self.store_name_edit)
        
        layout.addWidget(form_group)
        
        # カスタムフィールドフォーム
        if self.custom_fields_def:
            custom_group = QGroupBox("カスタムフィールド")
            custom_layout = QFormLayout(custom_group)
            
            self.custom_field_edits = {}
            for field_def in self.custom_fields_def:
                if field_def.get('is_active', 1):
                    field_name = field_def['field_name']
                    display_name = field_def['display_name']
                    field_type = field_def['field_type']
                    
                    if field_type in ['TEXT', 'DATE']:
                        edit = QLineEdit()
                    elif field_type == 'INTEGER':
                        edit = QLineEdit()
                        edit.setPlaceholderText("数値")
                    elif field_type == 'REAL':
                        edit = QLineEdit()
                        edit.setPlaceholderText("小数")
                    else:
                        edit = QLineEdit()
                    
                    custom_layout.addRow(f"{display_name}:", edit)
                    self.custom_field_edits[field_name] = edit
            
            layout.addWidget(custom_group)
        
        # ボタン
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_route_names(self):
        """既存のルート名一覧をロード"""
        route_names = self.db.get_route_names()
        self.affiliated_route_name_combo.clear()
        self.affiliated_route_name_combo.addItems(route_names)
    
    def on_route_name_changed(self, route_name: str):
        """ルート名が変更された時（プルダウン選択時）"""
        if not route_name:
            self.route_code_edit.clear()
            self.supplier_code_edit.clear()
            return
        
        # ルートコードを自動挿入
        route_code = self.db.get_route_code_by_name(route_name)
        if route_code:
            self.route_code_edit.setText(route_code)
        else:
            self.route_code_edit.clear()
        
        # 仕入れ先コードを自動生成
        next_supplier_code = self.db.get_next_supplier_code_for_route(route_name)
        if next_supplier_code:
            self.supplier_code_edit.setText(next_supplier_code)
        else:
            # ルートコードが取得できた場合は初期コードを生成
            if route_code:
                self.supplier_code_edit.setText(f"{route_code}-001")
            else:
                self.supplier_code_edit.clear()
    
    def on_route_name_text_changed(self, text: str):
        """ルート名が入力された時（テキスト編集時）"""
        # 既存ルート名と一致するかチェック
        current_index = self.affiliated_route_name_combo.findText(text)
        if current_index >= 0:
            # 既存ルートが見つかった場合は選択状態にする
            self.affiliated_route_name_combo.setCurrentIndex(current_index)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.store_data:
            return
        
        route_name = self.store_data.get('affiliated_route_name', '')
        if route_name:
            # 既存ルート名がリストにあるかチェック
            index = self.affiliated_route_name_combo.findText(route_name)
            if index >= 0:
                self.affiliated_route_name_combo.setCurrentIndex(index)
            else:
                # リストにない場合は現在のテキストとして設定
                self.affiliated_route_name_combo.setCurrentText(route_name)
        else:
            self.affiliated_route_name_combo.setCurrentText('')
        
        self.route_code_edit.setText(self.store_data.get('route_code', ''))
        self.supplier_code_edit.setText(self.store_data.get('supplier_code', ''))
        self.store_name_edit.setText(self.store_data.get('store_name', ''))
        
        # カスタムフィールドの読み込み
        custom_fields = self.store_data.get('custom_fields', {})
        for field_name, edit in self.custom_field_edits.items():
            value = custom_fields.get(field_name, '')
            edit.setText(str(value))
    
    def get_data(self) -> dict:
        """入力データを取得"""
        # 所属ルート名はQComboBoxから取得（編集可能なので現在のテキスト）
        route_name = self.affiliated_route_name_combo.currentText().strip()
        
        data = {
            'affiliated_route_name': route_name,
            'route_code': self.route_code_edit.text().strip(),
            'supplier_code': self.supplier_code_edit.text().strip(),
            'store_name': self.store_name_edit.text().strip(),
            'custom_fields': {}
        }
        
        # カスタムフィールドの取得
        for field_name, edit in self.custom_field_edits.items():
            data['custom_fields'][field_name] = edit.text().strip()
        
        return data
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        # 店舗名は必須
        if not data['store_name']:
            return False, "店舗名を入力してください"
        
        # 仕入れ先コードの重複チェック
        supplier_code = data['supplier_code']
        if supplier_code:
            exclude_id = self.store_data.get('id') if self.store_data else None
            if self.db.check_supplier_code_exists(supplier_code, exclude_id):
                return False, f"仕入れ先コード '{supplier_code}' は既に使用されています"
        
        return True, ""


class CustomFieldEditDialog(QDialog):
    """カスタムフィールド編集ダイアログ"""
    
    def __init__(self, parent=None, field_data=None):
        super().__init__(parent)
        self.field_data = field_data
        
        self.setWindowTitle("カスタムフィールド編集" if field_data else "カスタムフィールド追加")
        self.setModal(True)
        self.setup_ui()
        
        if field_data:
            self.load_data()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        self.field_name_edit = QLineEdit()
        self.field_name_edit.setPlaceholderText("field_name（英数字、アンダースコア）")
        form_layout.addRow("フィールド名:", self.field_name_edit)
        
        self.display_name_edit = QLineEdit()
        self.display_name_edit.setPlaceholderText("表示名（日本語OK）")
        form_layout.addRow("表示名:", self.display_name_edit)
        
        self.field_type_combo = QComboBox()
        self.field_type_combo.addItems(["TEXT", "INTEGER", "REAL", "DATE"])
        form_layout.addRow("フィールドタイプ:", self.field_type_combo)
        
        self.is_active_check = QCheckBox("有効")
        self.is_active_check.setChecked(True)
        form_layout.addRow("状態:", self.is_active_check)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        """既存データを読み込む"""
        if not self.field_data:
            return
        
        self.field_name_edit.setText(self.field_data.get('field_name', ''))
        self.field_name_edit.setEnabled(False)  # フィールド名は変更不可
        self.display_name_edit.setText(self.field_data.get('display_name', ''))
        self.field_type_combo.setCurrentText(self.field_data.get('field_type', 'TEXT'))
        self.is_active_check.setChecked(bool(self.field_data.get('is_active', 1)))
    
    def get_data(self) -> dict:
        """入力データを取得"""
        return {
            'field_name': self.field_name_edit.text().strip(),
            'display_name': self.display_name_edit.text().strip(),
            'field_type': self.field_type_combo.currentText(),
            'is_active': 1 if self.is_active_check.isChecked() else 0
        }
    
    def validate(self) -> Tuple[bool, str]:
        """入力データの検証"""
        data = self.get_data()
        
        if not data['field_name']:
            return False, "フィールド名を入力してください"
        
        if not data['display_name']:
            return False, "表示名を入力してください"
        
        # フィールド名の形式チェック（英数字とアンダースコアのみ）
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', data['field_name']):
            return False, "フィールド名は英数字とアンダースコアのみ使用できます"
        
        return True, ""


class StoreMasterWidget(QWidget):
    """店舗マスタ管理ウィジェット"""
    
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self.excel_importer = ExcelImporter()
        
        self.setup_ui()
        self.load_stores()
        self.load_custom_fields()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：操作ボタン
        self.setup_action_buttons(layout)
        
        # 中部：検索・フィルタ
        self.setup_search_filter(layout)
        
        # 下部：店舗一覧テーブル
        self.setup_store_table(layout)
        
        # 統計情報
        self.update_statistics()
    
    def setup_action_buttons(self, parent_layout):
        """操作ボタンの設定"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        # Excelインポートボタン
        import_btn = QPushButton("Excelインポート")
        import_btn.clicked.connect(self.import_excel)
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(import_btn)
        
        # 追加ボタン
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_store)
        button_layout.addWidget(add_btn)
        
        # 編集ボタン
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_store)
        button_layout.addWidget(edit_btn)
        
        # 削除ボタン
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_store)
        delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        button_layout.addWidget(delete_btn)
        
        button_layout.addStretch()
        
        # カスタムフィールド管理ボタン
        custom_fields_btn = QPushButton("カスタムフィールド管理")
        custom_fields_btn.clicked.connect(self.manage_custom_fields)
        button_layout.addWidget(custom_fields_btn)
        
        parent_layout.addWidget(button_group)
    
    def setup_search_filter(self, parent_layout):
        """検索・フィルタの設定"""
        search_group = QGroupBox("検索")
        search_layout = QHBoxLayout(search_group)
        
        search_label = QLabel("検索:")
        search_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("店舗名、仕入れ先コード、ルート名で検索...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.search_edit.clear)
        search_layout.addWidget(clear_btn)
        
        parent_layout.addWidget(search_group)
    
    def setup_store_table(self, parent_layout):
        """店舗一覧テーブルの設定"""
        table_group = QGroupBox("店舗一覧")
        table_layout = QVBoxLayout(table_group)
        
        self.store_table = QTableWidget()
        self.store_table.setAlternatingRowColors(True)
        self.store_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.store_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        # ソート機能を有効化
        self.store_table.setSortingEnabled(True)
        
        # ヘッダー設定
        header = self.store_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsClickable(True)  # ヘッダークリックでソート可能に
        
        table_layout.addWidget(self.store_table)
        
        # 統計情報ラベル
        self.stats_label = QLabel("統計: 読み込み中...")
        table_layout.addWidget(self.stats_label)
        
        parent_layout.addWidget(table_group)
    
    def load_stores(self, search_term: str = ""):
        """店舗一覧を読み込む"""
        stores = self.db.list_stores(search_term)
        self.update_table(stores)
        self.update_statistics()
    
    def load_custom_fields(self):
        """カスタムフィールド定義を読み込む"""
        self.custom_fields_def = self.db.list_custom_fields(active_only=True)
    
    def update_table(self, stores: list):
        """テーブルを更新"""
        # ソート機能を一時的に無効化（データ投入中はソートしない）
        self.store_table.setSortingEnabled(False)
        
        # カスタムフィールド定義を取得
        self.load_custom_fields()
        
        # 基本カラム + カスタムフィールドカラム
        basic_columns = ["ID", "所属ルート名", "ルートコード", "仕入れ先コード", "店舗名"]
        custom_columns = [field['display_name'] for field in self.custom_fields_def]
        columns = basic_columns + custom_columns
        
        self.store_table.setRowCount(len(stores))
        self.store_table.setColumnCount(len(columns))
        self.store_table.setHorizontalHeaderLabels(columns)
        
        # データの設定
        for i, store in enumerate(stores):
            # 基本カラム
            # IDは数値としてソートできるように設定
            id_item = QTableWidgetItem()
            id_item.setData(Qt.EditRole, store.get('id', 0))  # 数値として設定
            id_item.setText(str(store.get('id', '')))
            self.store_table.setItem(i, 0, id_item)
            
            self.store_table.setItem(i, 1, QTableWidgetItem(store.get('affiliated_route_name', '')))
            self.store_table.setItem(i, 2, QTableWidgetItem(store.get('route_code', '')))
            self.store_table.setItem(i, 3, QTableWidgetItem(store.get('supplier_code', '')))
            self.store_table.setItem(i, 4, QTableWidgetItem(store.get('store_name', '')))
            
            # カスタムフィールド
            custom_fields = store.get('custom_fields', {})
            for j, field_def in enumerate(self.custom_fields_def):
                col_idx = len(basic_columns) + j
                field_name = field_def['field_name']
                value = custom_fields.get(field_name, '')
                field_type = field_def.get('field_type', 'TEXT')
                
                # フィールドタイプに応じてデータ型を設定
                item = QTableWidgetItem()
                if field_type == 'INTEGER':
                    try:
                        int_value = int(value) if value else 0
                        item.setData(Qt.EditRole, int_value)
                    except (ValueError, TypeError):
                        item.setData(Qt.EditRole, 0)
                    item.setText(str(value) if value else '')
                elif field_type == 'REAL':
                    try:
                        float_value = float(value) if value else 0.0
                        item.setData(Qt.EditRole, float_value)
                    except (ValueError, TypeError):
                        item.setData(Qt.EditRole, 0.0)
                    item.setText(str(value) if value else '')
                else:
                    item.setText(str(value) if value else '')
                
                self.store_table.setItem(i, col_idx, item)
        
        # データ投入完了後、ソート機能を再有効化
        self.store_table.setSortingEnabled(True)
        
        # 列幅の自動調整
        self.store_table.resizeColumnsToContents()
    
    def update_statistics(self):
        """統計情報を更新"""
        stats = self.db.get_statistics()
        self.stats_label.setText(
            f"統計: 店舗数 {stats['total_stores']}件, "
            f"カスタムフィールド {stats['active_custom_fields']}件"
        )
    
    def on_search_changed(self, text):
        """検索テキスト変更時の処理"""
        self.load_stores(text)
    
    def import_excel(self):
        """Excelインポート"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Excelファイルを選択",
            r"D:\HIRIO\docs\参考データ",
            "Excelファイル (*.xlsx *.xlsm);;すべてのファイル (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Excelファイルを読み込む
            stores = self.excel_importer.read_store_master_sheet(file_path)
            
            if not stores:
                QMessageBox.information(self, "インポート", "読み込めるデータがありませんでした")
                return
            
            # データ検証
            validation = self.excel_importer.validate_store_data(stores)
            
            if validation['error_count'] > 0:
                error_msg = "\n".join(validation['errors'])
                QMessageBox.warning(
                    self,
                    "インポートエラー",
                    f"{validation['error_count']}件のエラーが見つかりました:\n\n{error_msg}"
                )
                return
            
            # 確認ダイアログ
            warning_msg = ""
            if validation['warning_count'] > 0:
                warning_msg = f"\n\n警告 {validation['warning_count']}件:\n" + "\n".join(validation['warnings'][:5])
            
            reply = QMessageBox.question(
                self,
                "インポート確認",
                f"{validation['valid_count']}件のデータをインポートしますか？{warning_msg}",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            # データをインポート
            imported_count = 0
            skipped_count = 0
            
            for store in stores:
                supplier_code = store.get('supplier_code')
                
                # 重複チェック
                if supplier_code and self.db.check_supplier_code_exists(supplier_code):
                    skipped_count += 1
                    continue
                
                try:
                    self.db.add_store(store)
                    imported_count += 1
                except Exception as e:
                    print(f"インポートエラー: {e}")
                    skipped_count += 1
            
            # 結果表示
            message = f"インポート完了\n\n追加: {imported_count}件"
            if skipped_count > 0:
                message += f"\nスキップ: {skipped_count}件（重複など）"
            
            QMessageBox.information(self, "インポート完了", message)
            
            # 一覧を再読み込み
            self.load_stores(self.search_edit.text())
            
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"Excelインポートに失敗しました:\n{str(e)}")
    
    def add_store(self):
        """店舗追加"""
        dialog = StoreEditDialog(self, custom_fields_def=self.custom_fields_def)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.add_store(data)
                QMessageBox.information(self, "完了", "店舗を追加しました")
                self.load_stores(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")
    
    def edit_store(self):
        """店舗編集"""
        selected_rows = self.store_table.selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "編集する店舗を選択してください")
            return
        
        row = selected_rows[0].row()
        store_id = int(self.store_table.item(row, 0).text())
        store_data = self.db.get_store(store_id)
        
        if not store_data:
            QMessageBox.warning(self, "エラー", "店舗データが見つかりません")
            return
        
        dialog = StoreEditDialog(self, store_data=store_data, custom_fields_def=self.custom_fields_def)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.update_store(store_id, data)
                QMessageBox.information(self, "完了", "店舗を更新しました")
                self.load_stores(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_store(self):
        """店舗削除"""
        selected_rows = self.store_table.selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する店舗を選択してください")
            return
        
        row = selected_rows[0].row()
        store_id = int(self.store_table.item(row, 0).text())
        store_name = self.store_table.item(row, 4).text()
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            f"店舗 '{store_name}' を削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            self.db.delete_store(store_id)
            QMessageBox.information(self, "完了", "店舗を削除しました")
            self.load_stores(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
    
    def manage_custom_fields(self):
        """カスタムフィールド管理"""
        from ui.custom_fields_dialog import CustomFieldsDialog
        dialog = CustomFieldsDialog(self, self.db)
        dialog.exec()
        self.load_stores(self.search_edit.text())  # カスタムフィールドが変わったので再読み込み

