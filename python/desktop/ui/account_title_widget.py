#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""勘定科目設定ウィジェット"""
from __future__ import annotations

import sys
import os
from typing import List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QTabWidget, QCheckBox, QDialog, QDialogButtonBox, QFormLayout
)

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.account_title_db import AccountTitleDatabase
from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state


class AccountTitleWidget(QWidget):
    """勘定科目マスタを編集するウィジェット"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = AccountTitleDatabase()
        self.setup_ui()
        self.refresh_table()
        self.refresh_credit_table()

        # テーブルの列幅を復元
        restore_table_header_state(self.table, "AccountTitleWidget/TableState")
        restore_table_header_state(self.credit_table, "AccountTitleWidget/CreditTableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "AccountTitleWidget/TableState")
        save_table_header_state(self.credit_table, "AccountTitleWidget/CreditTableState")

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # タブウィジェット
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # 借方勘定科目タブ
        self.debit_tab = QWidget()
        self.setup_debit_tab()
        self.tab_widget.addTab(self.debit_tab, "借方勘定科目")

        # 貸方勘定科目タブ
        self.credit_tab = QWidget()
        self.setup_credit_tab()
        self.tab_widget.addTab(self.credit_tab, "貸方勘定科目")
    
    def setup_debit_tab(self) -> None:
        layout = QVBoxLayout(self.debit_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 追加エリア
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("科目名:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: 仕入, 消耗品費, 旅費交通費")
        add_layout.addWidget(self.name_edit)

        self.add_btn = QPushButton("追加")
        self.add_btn.clicked.connect(self.add_title)
        add_layout.addWidget(self.add_btn)
        add_layout.addStretch()
        layout.addLayout(add_layout)

        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["ID", "科目名"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnHidden(0, True)
        layout.addWidget(self.table)

        # 削除ボタン
        btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("選択行を削除")
        self.delete_btn.clicked.connect(self.delete_selected)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
    
    def setup_credit_tab(self) -> None:
        layout = QVBoxLayout(self.credit_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 追加エリア
        add_layout = QHBoxLayout()
        self.add_credit_btn = QPushButton("追加")
        self.add_credit_btn.clicked.connect(self.add_credit_account)
        add_layout.addWidget(self.add_credit_btn)
        add_layout.addStretch()
        layout.addLayout(add_layout)

        # テーブル
        self.credit_table = QTableWidget()
        self.credit_table.setColumnCount(6)
        self.credit_table.setHorizontalHeaderLabels(["ID", "科目名", "クレジットカード名", "下四桁", "デフォルト", "メモ"])
        self.credit_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.credit_table.setSelectionMode(QTableWidget.SingleSelection)
        self.credit_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.credit_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.credit_table.setColumnHidden(0, True)
        layout.addWidget(self.credit_table)

        # ボタン
        btn_layout = QHBoxLayout()
        self.edit_credit_btn = QPushButton("編集")
        self.edit_credit_btn.clicked.connect(self.edit_credit_account)
        btn_layout.addWidget(self.edit_credit_btn)
        self.delete_credit_btn = QPushButton("選択行を削除")
        self.delete_credit_btn.clicked.connect(self.delete_credit_selected)
        btn_layout.addWidget(self.delete_credit_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def refresh_table(self) -> None:
        titles = self.db.list_titles()
        self.table.setRowCount(len(titles))
        for row, t in enumerate(titles):
            id_item = QTableWidgetItem(str(t.get("id")))
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(t.get("name", "")))

    def add_title(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "警告", "科目名を入力してください。")
            return
        try:
            self.db.add_title(name)
            self.name_edit.clear()
            self.refresh_table()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"科目の追加に失敗しました:\n{e}")

    def delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "警告", "削除する行を選択してください。")
            return
        id_item = self.table.item(row, 0)
        if not id_item:
            return
        try:
            title_id = int(id_item.text())
        except ValueError:
            return
        if QMessageBox.question(
            self,
            "確認",
            "選択した科目を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        if self.db.delete_title(title_id):
            self.refresh_table()
        else:
            QMessageBox.warning(self, "警告", "削除できませんでした。")
    
    def refresh_credit_table(self) -> None:
        accounts = self.db.list_credit_accounts()
        self.credit_table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            self.credit_table.setItem(row, 0, QTableWidgetItem(str(account.get("id"))))
            self.credit_table.setItem(row, 1, QTableWidgetItem(account.get("name", "")))
            self.credit_table.setItem(row, 2, QTableWidgetItem(account.get("card_name", "")))
            self.credit_table.setItem(row, 3, QTableWidgetItem(account.get("last_four_digits", "")))
            default_item = QTableWidgetItem("✓" if account.get("is_default") else "")
            self.credit_table.setItem(row, 4, default_item)
            self.credit_table.setItem(row, 5, QTableWidgetItem(account.get("note", "")))
    
    def add_credit_account(self) -> None:
        dialog = CreditAccountDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if data:
                try:
                    self.db.add_credit_account(
                        data["name"],
                        data.get("card_name", ""),
                        data.get("last_four_digits", ""),
                        data.get("is_default", False),
                        data.get("note", "")
                    )
                    self.refresh_credit_table()
                except Exception as e:
                    QMessageBox.critical(self, "エラー", f"追加に失敗しました:\n{e}")
    
    def edit_credit_account(self) -> None:
        row = self.credit_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "警告", "編集する行を選択してください。")
            return
        id_item = self.credit_table.item(row, 0)
        if not id_item:
            return
        try:
            account_id = int(id_item.text())
        except ValueError:
            return
        
        accounts = self.db.list_credit_accounts()
        account = next((a for a in accounts if a.get("id") == account_id), None)
        if not account:
            return
        
        dialog = CreditAccountDialog(self, account)
        if dialog.exec():
            data = dialog.get_data()
            if data:
                try:
                    self.db.update_credit_account(
                        account_id,
                        name=data.get("name"),
                        card_name=data.get("card_name", ""),
                        last_four_digits=data.get("last_four_digits", ""),
                        is_default=data.get("is_default", False),
                        note=data.get("note", "")
                    )
                    self.refresh_credit_table()
                except Exception as e:
                    QMessageBox.critical(self, "エラー", f"更新に失敗しました:\n{e}")
    
    def delete_credit_selected(self) -> None:
        row = self.credit_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "警告", "削除する行を選択してください。")
            return
        id_item = self.credit_table.item(row, 0)
        if not id_item:
            return
        try:
            account_id = int(id_item.text())
        except ValueError:
            return
        if QMessageBox.question(
            self,
            "確認",
            "選択した科目を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        if self.db.delete_credit_account(account_id):
            self.refresh_credit_table()
        else:
            QMessageBox.warning(self, "警告", "削除できませんでした。")


class CreditAccountDialog(QDialog):
    """貸方勘定科目編集ダイアログ"""
    
    def __init__(self, parent=None, account: Dict[str, Any] = None):
        super().__init__(parent)
        self.account = account
        self.setWindowTitle("貸方勘定科目編集" if account else "貸方勘定科目追加")
        self.setup_ui()
        if account:
            self.load_data()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: 現金, 預金, クレジットカード名")
        form_layout.addRow("科目名:", self.name_edit)
        
        self.card_name_edit = QLineEdit()
        self.card_name_edit.setPlaceholderText("例: 楽天カード, 三井住友カード")
        form_layout.addRow("クレジットカード名:", self.card_name_edit)
        
        self.last_four_edit = QLineEdit()
        self.last_four_edit.setPlaceholderText("例: 1234")
        form_layout.addRow("下四桁:", self.last_four_edit)
        
        self.default_check = QCheckBox("デフォルトに設定")
        # チェックボックスのテキスト色を設定（白背景で見えるように）
        self.default_check.setStyleSheet("QCheckBox { color: black; }")
        form_layout.addRow("", self.default_check)
        
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("メモ（任意）")
        form_layout.addRow("メモ:", self.note_edit)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def load_data(self):
        if not self.account:
            return
        self.name_edit.setText(self.account.get("name", ""))
        self.card_name_edit.setText(self.account.get("card_name", ""))
        self.last_four_edit.setText(self.account.get("last_four_digits", ""))
        self.default_check.setChecked(bool(self.account.get("is_default")))
        self.note_edit.setText(self.account.get("note", ""))
    
    def get_data(self) -> Dict[str, Any]:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "入力エラー", "科目名を入力してください。")
            return None
        return {
            "name": name,
            "card_name": self.card_name_edit.text().strip(),
            "last_four_digits": self.last_four_edit.text().strip(),
            "is_default": self.default_check.isChecked(),
            "note": self.note_edit.text().strip()
        }

