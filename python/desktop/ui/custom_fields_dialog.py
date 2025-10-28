#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
カスタムフィールド管理ダイアログ

カスタムフィールドの追加・編集・削除機能
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QGroupBox, QLabel
)
from PySide6.QtCore import Qt
from database.store_db import StoreDatabase
from ui.store_master_widget import CustomFieldEditDialog


class CustomFieldsDialog(QDialog):
    """カスタムフィールド管理ダイアログ"""
    
    def __init__(self, parent=None, db: StoreDatabase = None):
        super().__init__(parent)
        self.db = db or StoreDatabase()
        
        self.setWindowTitle("カスタムフィールド管理")
        self.setModal(True)
        self.resize(700, 500)
        self.setup_ui()
        self.load_fields()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        # 説明
        info_label = QLabel(
            "カスタムフィールドは店舗情報に追加できる項目です。\n"
            "例: 住所、電話番号、メモなど"
        )
        layout.addWidget(info_label)
        
        # テーブル
        table_group = QGroupBox("カスタムフィールド一覧")
        table_layout = QVBoxLayout(table_group)
        
        self.fields_table = QTableWidget()
        self.fields_table.setAlternatingRowColors(True)
        self.fields_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.fields_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        columns = ["ID", "フィールド名", "表示名", "タイプ", "状態"]
        self.fields_table.setColumnCount(len(columns))
        self.fields_table.setHorizontalHeaderLabels(columns)
        
        header = self.fields_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        table_layout.addWidget(self.fields_table)
        layout.addWidget(table_group)
        
        # ボタン
        button_layout = QHBoxLayout()
        
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_field)
        button_layout.addWidget(add_btn)
        
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_field)
        button_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_field)
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
        
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def load_fields(self):
        """カスタムフィールド一覧を読み込む"""
        fields = self.db.list_custom_fields(active_only=False)
        
        self.fields_table.setRowCount(len(fields))
        
        for i, field in enumerate(fields):
            self.fields_table.setItem(i, 0, QTableWidgetItem(str(field.get('id', ''))))
            self.fields_table.setItem(i, 1, QTableWidgetItem(field.get('field_name', '')))
            self.fields_table.setItem(i, 2, QTableWidgetItem(field.get('display_name', '')))
            self.fields_table.setItem(i, 3, QTableWidgetItem(field.get('field_type', '')))
            
            is_active = "有効" if field.get('is_active', 1) else "無効"
            status_item = QTableWidgetItem(is_active)
            if not field.get('is_active', 1):
                status_item.setForeground(Qt.red)
            self.fields_table.setItem(i, 4, status_item)
        
        self.fields_table.resizeColumnsToContents()
    
    def add_field(self):
        """カスタムフィールド追加"""
        dialog = CustomFieldEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.add_custom_field(data)
                QMessageBox.information(self, "完了", "カスタムフィールドを追加しました")
                self.load_fields()
            except Exception as e:
                error_msg = str(e)
                if "UNIQUE constraint failed" in error_msg:
                    QMessageBox.warning(self, "エラー", "このフィールド名は既に使用されています")
                else:
                    QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{error_msg}")
    
    def edit_field(self):
        """カスタムフィールド編集"""
        selected_rows = self.fields_table.selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "編集するフィールドを選択してください")
            return
        
        row = selected_rows[0].row()
        field_id = int(self.fields_table.item(row, 0).text())
        field_data = self.db.get_custom_field(field_id)
        
        if not field_data:
            QMessageBox.warning(self, "エラー", "フィールドデータが見つかりません")
            return
        
        dialog = CustomFieldEditDialog(self, field_data=field_data)
        if dialog.exec() == QDialog.Accepted:
            is_valid, error_msg = dialog.validate()
            if not is_valid:
                QMessageBox.warning(self, "エラー", error_msg)
                return
            
            try:
                data = dialog.get_data()
                self.db.update_custom_field(field_id, data)
                QMessageBox.information(self, "完了", "カスタムフィールドを更新しました")
                self.load_fields()
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_field(self):
        """カスタムフィールド削除"""
        selected_rows = self.fields_table.selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除するフィールドを選択してください")
            return
        
        row = selected_rows[0].row()
        field_id = int(self.fields_table.item(row, 0).text())
        field_name = self.fields_table.item(row, 2).text()
        
        reply = QMessageBox.question(
            self,
            "削除確認",
            f"カスタムフィールド '{field_name}' を削除しますか？\n\n"
            "注意: 削除すると、このフィールドに保存されているデータも失われます。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            self.db.delete_custom_field(field_id)
            QMessageBox.information(self, "完了", "カスタムフィールドを削除しました")
            self.load_fields()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")

