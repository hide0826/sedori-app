#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""経費先マスタ（編集ダイアログ・一覧）。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QLineEdit,
    QLabel, QGroupBox, QFileDialog, QTextEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QTabWidget,
    QProgressDialog, QApplication, QListWidget, QListWidgetItem,
    QSplitter, QDoubleSpinBox, QAbstractItemView, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QSettings
from PySide6.QtGui import QColor, QDrag
from typing import Tuple, List, Dict, Any, Optional
import sys
import os
import re
import webbrowser

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from utils.excel_importer import ExcelImporter
from utils.ui_utils import reapply_table_column_widths

from .support import (
    get_store_info_from_google,
    recover_store_info_with_japanese,
    normalize_stored_japanese_address,
)


class ExpenseDestinationEditDialog(QDialog):
    """経費先編集ダイアログ（名称入力時にチェーン店コードマッピングを参照して経費先コードを自動入力）"""
    
    def __init__(self, parent=None, dest_data=None):
        super().__init__(parent)
        self.dest_data = dest_data
        self.account_db = AccountTitleDatabase()
        self.store_db = StoreDatabase()
        self.setWindowTitle("経費先編集" if dest_data else "経費先追加")
        self.setModal(True)
        self.setup_ui()
        if dest_data:
            self.load_data()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        form_group = QGroupBox("基本情報")
        form_layout = QFormLayout(form_group)
        
        self.journal_combo = QComboBox()
        self.journal_combo.setEditable(True)
        titles = self.account_db.list_titles()
        for t in titles:
            self.journal_combo.addItem(t.get("name", ""))
        form_layout.addRow("科目（勘定科目）:", self.journal_combo)
        
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("経費先コード（任意）")
        form_layout.addRow("経費先コード:", self.code_edit)
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("名称（例: コーナン本羽田店）")
        self.name_edit.textChanged.connect(self._on_name_changed_for_code)
        form_layout.addRow("名称:", self.name_edit)
        
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("住所")
        form_layout.addRow("住所:", self.address_edit)
        
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("電話番号")
        form_layout.addRow("電話番号:", self.phone_edit)
        
        self.registration_edit = QLineEdit()
        self.registration_edit.setPlaceholderText("登録番号（任意）")
        form_layout.addRow("登録番号:", self.registration_edit)
        
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("備考")
        form_layout.addRow("備考:", self.notes_edit)
        
        layout.addWidget(form_group)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _on_name_changed_for_code(self, name: str):
        """名称入力時にチェーン店コードマッピングを参照し、経費先コードを自動入力（既存は連番）"""
        name = (name or "").strip()
        if not name:
            return
        try:
            code = self.store_db.get_next_expense_destination_code_from_name(name)
            if code:
                self.code_edit.setText(code)
        except Exception:
            pass
    
    def load_data(self):
        if not self.dest_data:
            return
        self.journal_combo.setCurrentText(self.dest_data.get("journal") or "")
        self.code_edit.setText(self.dest_data.get("code") or "")
        self.name_edit.blockSignals(True)
        self.name_edit.setText(self.dest_data.get("name") or "")
        self.name_edit.blockSignals(False)
        self.address_edit.setText(self.dest_data.get("address") or "")
        self.phone_edit.setText(self.dest_data.get("phone") or "")
        self.registration_edit.setText(self.dest_data.get("registration_number") or "")
        self.notes_edit.setText(self.dest_data.get("notes") or "")
    
    def get_data(self) -> Dict[str, Any]:
        name = self.name_edit.text().strip()
        if not name:
            return {}
        return {
            "journal": self.journal_combo.currentText().strip(),
            "code": self.code_edit.text().strip(),
            "name": name,
            "address": self.address_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "registration_number": self.registration_edit.text().strip(),
            "notes": self.notes_edit.text().strip(),
        }


class ExpenseDestinationListWidget(QWidget):
    """経費先一覧ウィジェット（店舗一覧と同様のUI、ルート関連なし・科目列あり）"""
    
    def __init__(self):
        super().__init__()
        self.db = StoreDatabase()
        self.setup_ui()
        self.load_destinations()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setup_action_buttons(layout)
        self.setup_search_filter(layout)
        self.setup_info_bar(layout)
        self.setup_destinations_table(layout)
        self.update_statistics()
    
    def setup_action_buttons(self, parent_layout):
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        add_btn = QPushButton("追加")
        add_btn.clicked.connect(self.add_destination)
        button_layout.addWidget(add_btn)
        edit_btn = QPushButton("編集")
        edit_btn.clicked.connect(self.edit_destination)
        button_layout.addWidget(edit_btn)
        delete_btn = QPushButton("削除")
        delete_btn.clicked.connect(self.delete_destination)
        delete_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; padding: 8px 16px; border-radius: 4px; }")
        button_layout.addWidget(delete_btn)
        button_layout.addStretch()
        parent_layout.addWidget(button_group)
    
    def setup_search_filter(self, parent_layout):
        search_group = QGroupBox("検索")
        search_layout = QHBoxLayout(search_group)
        search_layout.addWidget(QLabel("検索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("名称、経費先コード、科目で検索...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_edit)
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.search_edit.clear)
        search_layout.addWidget(clear_btn)
        parent_layout.addWidget(search_group)
    
    def setup_info_bar(self, parent_layout):
        info_group = QGroupBox("情報取得")
        info_layout = QHBoxLayout(info_group)
        fetch_info_btn = QPushButton("情報取得")
        fetch_info_btn.clicked.connect(self.fetch_missing_destination_info)
        fetch_info_btn.setStyleSheet("""
            QPushButton { background-color: #ffc107; color: #212529; padding: 8px 16px; border-radius: 4px; min-width: 120px; font-weight: bold; }
            QPushButton:hover { background-color: #e0a800; }
        """)
        info_layout.addWidget(fetch_info_btn)
        info_layout.addStretch()
        parent_layout.addWidget(info_group)
    
    def setup_destinations_table(self, parent_layout):
        table_group = QGroupBox("経費先一覧")
        table_layout = QVBoxLayout(table_group)
        self.dest_table = QTableWidget()
        self.dest_table.setAlternatingRowColors(True)
        self.dest_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dest_table.setEditTriggers(QTableWidget.DoubleClicked)
        self.dest_table.setTextElideMode(Qt.ElideNone)
        self.dest_table.setWordWrap(True)
        self.dest_table.setSortingEnabled(True)
        header = self.dest_table.horizontalHeader()
        header.setSectionsClickable(True)
        self.dest_table.cellChanged.connect(self.on_dest_cell_changed)
        table_layout.addWidget(self.dest_table)
        self.dest_stats_label = QLabel("統計: 読み込み中...")
        table_layout.addWidget(self.dest_stats_label)
        parent_layout.addWidget(table_group)
    
    def load_destinations(self, search_term: str = ""):
        destinations = self.db.list_expense_destinations(search_term)
        self.update_destinations_table(destinations)
        self.update_statistics()
    
    def on_search_changed(self, text):
        self.load_destinations(text)
    
    def update_destinations_table(self, destinations: list):
        columns = ["ID", "科目", "経費先コード", "名称", "住所", "電話番号", "登録番号", "備考"]
        self.dest_table.setSortingEnabled(False)
        self.dest_table.setRowCount(len(destinations))
        self.dest_table.setColumnCount(len(columns))
        self.dest_table.setHorizontalHeaderLabels(columns)
        self.dest_table.blockSignals(True)
        for i, d in enumerate(destinations):
            self.dest_table.setItem(i, 0, QTableWidgetItem(str(d.get("id", ""))))
            self.dest_table.setItem(i, 1, QTableWidgetItem(d.get("journal") or ""))
            self.dest_table.setItem(i, 2, QTableWidgetItem(d.get("code") or ""))
            self.dest_table.setItem(i, 3, QTableWidgetItem(d.get("name") or ""))
            self.dest_table.setItem(i, 4, QTableWidgetItem(d.get("address") or ""))
            self.dest_table.setItem(i, 5, QTableWidgetItem(d.get("phone") or ""))
            self.dest_table.setItem(i, 6, QTableWidgetItem(d.get("registration_number") or ""))
            notes_item = QTableWidgetItem(d.get("notes") or "")
            notes_item.setData(Qt.UserRole, d.get("id"))
            self.dest_table.setItem(i, 7, notes_item)
        self.dest_table.blockSignals(False)
        self.dest_table.setSortingEnabled(True)
        reapply_table_column_widths(self.dest_table)
        self.dest_table.resizeRowsToContents()
    
    def update_statistics(self):
        destinations = self.db.list_expense_destinations()
        self.dest_stats_label.setText(f"統計: 経費先 {len(destinations)} 件")
    
    def add_destination(self):
        dialog = ExpenseDestinationEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data:
                QMessageBox.warning(self, "入力エラー", "名称を入力してください。")
                return
            try:
                if data.get("code") and self.db.check_expense_destination_code_exists(data["code"]):
                    QMessageBox.warning(self, "重複", "その経費先コードは既に登録されています。")
                    return
                self.db.add_expense_destination(data)
                QMessageBox.information(self, "完了", "経費先を追加しました。")
                self.load_destinations(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{str(e)}")
    
    def edit_destination(self):
        selected = self.dest_table.selectionModel().selectedRows() if self.dest_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "編集する経費先を選択してください。")
            return
        row = selected[0].row()
        id_item = self.dest_table.item(row, 0)
        if not id_item or not id_item.text().strip():
            return
        try:
            dest_id = int(id_item.text())
        except ValueError:
            return
        dest_data = self.db.get_expense_destination(dest_id)
        if not dest_data:
            return
        dialog = ExpenseDestinationEditDialog(self, dest_data=dest_data)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data:
                return
            try:
                if data.get("code") and self.db.check_expense_destination_code_exists(data["code"], exclude_id=dest_id):
                    QMessageBox.warning(self, "重複", "その経費先コードは既に登録されています。")
                    return
                self.db.update_expense_destination(dest_id, data)
                QMessageBox.information(self, "完了", "経費先を更新しました。")
                self.load_destinations(self.search_edit.text())
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{str(e)}")
    
    def delete_destination(self):
        selected = self.dest_table.selectionModel().selectedRows() if self.dest_table.selectionModel() else []
        if not selected:
            QMessageBox.warning(self, "警告", "削除する経費先を選択してください。")
            return
        row = selected[0].row()
        id_item = self.dest_table.item(row, 0)
        if not id_item:
            return
        try:
            dest_id = int(id_item.text())
        except ValueError:
            return
        name = self.dest_table.item(row, 3).text() if self.dest_table.item(row, 3) else ""
        if QMessageBox.question(self, "削除確認", f"経費先「{name}」を削除しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.db.delete_expense_destination(dest_id)
            QMessageBox.information(self, "完了", "経費先を削除しました。")
            self.load_destinations(self.search_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{str(e)}")
    
    def fetch_missing_destination_info(self):
        """住所・電話番号が欠けている経費先の情報をGoogle Maps APIから取得（店舗一覧と同じ機能）"""
        def safe_strip(value):
            if value is None:
                return ''
            return str(value).strip() if isinstance(value, str) else ''
        if get_store_info_from_google is None:
            QMessageBox.warning(self, "エラー", "Google Mapsサービスモジュールが読み込めませんでした。\ngooglemapsライブラリがインストールされているか確認してください。")
            return
        destinations = self.db.list_expense_destinations(self.search_edit.text())
        missing = [d for d in destinations if d.get("name") and (not safe_strip(d.get("address")) or not safe_strip(d.get("phone")))]
        if not missing:
            QMessageBox.information(self, "情報", "住所・電話番号が欠けている経費先はありません。")
            return
        if QMessageBox.question(self, "確認", f"{len(missing)}件の経費先の情報を取得しますか？\n（Google Maps APIを使用します）", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        progress = QProgressDialog("経費先情報を取得中...", "キャンセル", 0, len(missing), self)
        progress.setWindowTitle("情報取得中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        updated_count = 0
        failed_count = 0
        for i, d in enumerate(missing):
            if progress.wasCanceled():
                break
            dest_id = d.get("id")
            name = safe_strip(d.get("name"))
            current_address = safe_strip(d.get("address"))
            current_phone = safe_strip(d.get("phone"))
            progress.setValue(i)
            progress.setLabelText(f"取得中: {name}")
            QApplication.processEvents()
            info = get_store_info_from_google(name, language_code='ja')
            if info:
                addr = (info.get("address") or "") if not current_address else current_address
                phone = (info.get("phone") or "") if not current_phone else current_phone
                if addr or phone:
                    try:
                        self.db.update_expense_destination_address_phone(dest_id, addr, phone)
                        updated_count += 1
                    except Exception as e:
                        print(f"経費先情報更新エラー (ID: {dest_id}): {e}")
                        failed_count += 1
            else:
                failed_count += 1
        progress.setValue(len(missing))
        progress.close()
        QMessageBox.information(self, "完了", f"情報取得が完了しました。\n\n更新: {updated_count}件\n失敗: {failed_count}件")
        self.load_destinations(self.search_edit.text())
    
    def on_dest_cell_changed(self, row: int, column: int):
        """備考列の変更時のみDBに保存"""
        if column != 7:
            return
        try:
            item = self.dest_table.item(row, 7)
            if not item:
                return
            id_item = self.dest_table.item(row, 0)
            if not id_item:
                return
            dest_id = int(id_item.text())
            dest = self.db.get_expense_destination(dest_id)
            if not dest:
                return
            new_notes = item.text()
            self.db.update_expense_destination(dest_id, {
                "journal": dest.get("journal") or "",
                "code": dest.get("code") or "",
                "name": dest.get("name") or "",
                "address": dest.get("address") or "",
                "phone": dest.get("phone") or "",
                "registration_number": dest.get("registration_number") or "",
                "notes": new_notes,
            })
        except Exception as e:
            print(f"経費先備考保存エラー: {e}")
