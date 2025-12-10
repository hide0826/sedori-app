#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
経費管理ウィジェット

経費の登録・一覧表示・編集・削除機能を提供
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QFileDialog, QDialog, QDialogButtonBox, QFormLayout,
    QLineEdit, QComboBox, QSpinBox, QTextEdit, QDateEdit
)
from PySide6.QtGui import QPixmap

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.expense_db import ExpenseDatabase
from database.receipt_db import ReceiptDatabase
from database.store_db import StoreDatabase
from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state


class ExpenseWidget(QWidget):
    """経費管理ウィジェット"""
    
    def __init__(self, api_client=None):
        super().__init__()
        self.api_client = api_client
        self.expense_db = ExpenseDatabase()
        self.receipt_db = ReceiptDatabase()
        self.store_db = StoreDatabase()
        
        # 経費カテゴリの定義
        self.expense_categories = [
            "消耗品費",
            "旅費交通費",
            "通信費",
            "光熱費",
            "広告宣伝費",
            "その他"
        ]
        
        self.setup_ui()
        self.refresh_table()

        # テーブルの列幅を復元
        restore_table_header_state(self.table, "ExpenseWidget/TableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "ExpenseWidget/TableState")

    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部：ボタンエリア
        button_layout = QHBoxLayout()
        self.add_btn = QPushButton("経費を追加")
        self.add_btn.clicked.connect(self.show_add_dialog)
        button_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("編集")
        self.edit_btn.clicked.connect(self.show_edit_dialog)
        button_layout.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("削除")
        self.delete_btn.clicked.connect(self.delete_expense)
        button_layout.addWidget(self.delete_btn)

        button_layout.addStretch()

        # 期間フィルタ
        filter_label = QLabel("期間:")
        button_layout.addWidget(filter_label)

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addYears(-1))
        button_layout.addWidget(self.start_date_edit)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate())
        button_layout.addWidget(self.end_date_edit)

        self.filter_btn = QPushButton("フィルタ")
        self.filter_btn.clicked.connect(self.refresh_table)
        button_layout.addWidget(self.filter_btn)

        layout.addLayout(button_layout)

        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "日付", "カテゴリ", "勘定科目", "支払先", "金額", "数量", "単価", "支払方法", "メモ"
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.show_edit_dialog)
        layout.addWidget(self.table)

    def refresh_table(self):
        """テーブルを更新"""
        # 期間フィルタを取得
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        
        expenses = self.expense_db.list_by_date(start_date=start_date, end_date=end_date)
        
        self.table.setRowCount(len(expenses))
        
        for row, expense in enumerate(expenses):
            self.table.setItem(row, 0, QTableWidgetItem(expense.get("expense_date", "")))
            self.table.setItem(row, 1, QTableWidgetItem(expense.get("expense_category", "")))
            self.table.setItem(row, 2, QTableWidgetItem(expense.get("account_title", "")))
            self.table.setItem(row, 3, QTableWidgetItem(expense.get("store_name", "")))
            self.table.setItem(row, 4, QTableWidgetItem(str(expense.get("amount", 0))))
            self.table.setItem(row, 5, QTableWidgetItem(str(expense.get("quantity", 1))))
            self.table.setItem(row, 6, QTableWidgetItem(str(expense.get("unit_price", "")) if expense.get("unit_price") else ""))
            self.table.setItem(row, 7, QTableWidgetItem(expense.get("payment_method", "")))
            self.table.setItem(row, 8, QTableWidgetItem(expense.get("memo", "")))
            
            # 行データにIDを保存
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, expense.get("id"))

    def show_add_dialog(self):
        """追加ダイアログを表示"""
        dialog = ExpenseEditDialog(self, expense_categories=self.expense_categories, receipt_db=self.receipt_db, store_db=self.store_db)
        if dialog.exec() == QDialog.Accepted:
            expense_data = dialog.get_expense_data()
            try:
                self.expense_db.upsert(expense_data)
                self.refresh_table()
                QMessageBox.information(self, "完了", "経費を追加しました。")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"経費の追加に失敗しました:\n{e}")

    def show_edit_dialog(self):
        """編集ダイアログを表示"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "編集する経費を選択してください。")
            return
        
        # 行からIDを取得
        item = self.table.item(current_row, 0)
        if not item:
            return
        
        expense_id = item.data(Qt.UserRole)
        if not expense_id:
            return
        
        expense = self.expense_db.get_by_id(expense_id)
        if not expense:
            QMessageBox.warning(self, "警告", "経費情報が見つかりません。")
            return
        
        dialog = ExpenseEditDialog(self, expense=expense, expense_categories=self.expense_categories, receipt_db=self.receipt_db, store_db=self.store_db)
        if dialog.exec() == QDialog.Accepted:
            expense_data = dialog.get_expense_data()
            expense_data["id"] = expense_id
            try:
                self.expense_db.upsert(expense_data)
                self.refresh_table()
                QMessageBox.information(self, "完了", "経費を更新しました。")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"経費の更新に失敗しました:\n{e}")

    def delete_expense(self):
        """経費を削除"""
        current_row = self.table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "警告", "削除する経費を選択してください。")
            return
        
        # 行からIDを取得
        item = self.table.item(current_row, 0)
        if not item:
            return
        
        expense_id = item.data(Qt.UserRole)
        if not expense_id:
            return
        
        reply = QMessageBox.question(
            self, "確認", "この経費を削除しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.expense_db.delete(expense_id)
                self.refresh_table()
                QMessageBox.information(self, "完了", "経費を削除しました。")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"経費の削除に失敗しました:\n{e}")


class ExpenseEditDialog(QDialog):
    """経費編集ダイアログ"""
    
    def __init__(self, parent=None, expense: Optional[Dict[str, Any]] = None, expense_categories: List[str] = None, receipt_db=None, store_db=None):
        super().__init__(parent)
        self.expense = expense
        self.expense_categories = expense_categories or []
        self.receipt_db = receipt_db
        self.store_db = store_db
        
        self.setWindowTitle("経費を追加" if not expense else "経費を編集")
        self.setMinimumWidth(500)
        self.setup_ui()
        
        if expense:
            self.load_expense_data(expense)

    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        
        form = QFormLayout()
        
        # 日付
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        form.addRow("日付:", self.date_edit)
        
        # カテゴリ
        self.category_combo = QComboBox()
        self.category_combo.addItems(self.expense_categories)
        form.addRow("カテゴリ:", self.category_combo)
        
        # 勘定科目
        self.account_title_edit = QLineEdit()
        self.account_title_edit.setPlaceholderText("例: 仕入、消耗品費、旅費交通費")
        form.addRow("勘定科目:", self.account_title_edit)
        
        # 支払先名
        self.store_name_edit = QLineEdit()
        form.addRow("支払先名:", self.store_name_edit)
        
        # 金額
        self.amount_spin = QSpinBox()
        self.amount_spin.setMinimum(0)
        self.amount_spin.setMaximum(99999999)
        form.addRow("金額:", self.amount_spin)
        
        # 数量
        self.quantity_spin = QSpinBox()
        self.quantity_spin.setMinimum(1)
        self.quantity_spin.setMaximum(9999)
        self.quantity_spin.setValue(1)
        form.addRow("数量:", self.quantity_spin)
        
        # 単価
        self.unit_price_spin = QSpinBox()
        self.unit_price_spin.setMinimum(0)
        self.unit_price_spin.setMaximum(99999999)
        form.addRow("単価:", self.unit_price_spin)
        
        # 支払方法
        self.payment_method_combo = QComboBox()
        self.payment_method_combo.addItems(["現金", "クレジットカード", "QR決済", "電子マネー", "その他"])
        form.addRow("支払方法:", self.payment_method_combo)
        
        # レシートID（手動入力または選択）
        receipt_layout = QHBoxLayout()
        self.receipt_id_edit = QLineEdit()
        self.receipt_id_edit.setPlaceholderText("レシートID（オプション）")
        receipt_layout.addWidget(self.receipt_id_edit)
        self.receipt_select_btn = QPushButton("レシート選択")
        self.receipt_select_btn.clicked.connect(self.select_receipt)
        receipt_layout.addWidget(self.receipt_select_btn)
        form.addRow("レシート:", receipt_layout)
        
        # メモ
        self.memo_edit = QTextEdit()
        self.memo_edit.setMaximumHeight(100)
        form.addRow("メモ:", self.memo_edit)
        
        layout.addLayout(form)
        
        # ボタン
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def load_expense_data(self, expense: Dict[str, Any]):
        """経費データを読み込む"""
        if expense.get("expense_date"):
            date = QDate.fromString(expense["expense_date"], "yyyy-MM-dd")
            if date.isValid():
                self.date_edit.setDate(date)
        
        category = expense.get("expense_category", "")
        if category in self.expense_categories:
            index = self.expense_categories.index(category)
            self.category_combo.setCurrentIndex(index)
        
        self.account_title_edit.setText(expense.get("account_title", ""))
        self.store_name_edit.setText(expense.get("store_name", ""))
        self.amount_spin.setValue(expense.get("amount", 0))
        self.quantity_spin.setValue(expense.get("quantity", 1))
        if expense.get("unit_price"):
            self.unit_price_spin.setValue(expense["unit_price"])
        
        payment_method = expense.get("payment_method", "")
        payment_methods = ["現金", "クレジットカード", "QR決済", "電子マネー", "その他"]
        if payment_method in payment_methods:
            index = payment_methods.index(payment_method)
            self.payment_method_combo.setCurrentIndex(index)
        
        if expense.get("receipt_id"):
            receipt = self.receipt_db.get_receipt(expense["receipt_id"])
            if receipt:
                self.receipt_id_edit.setText(receipt.get("receipt_id", ""))
        
        self.memo_edit.setPlainText(expense.get("memo", ""))

    def select_receipt(self):
        """レシートを選択"""
        # 簡易実装：レシートIDを手動入力
        # 将来的にはレシート一覧から選択できるようにする
        QMessageBox.information(
            self, "情報",
            "レシートIDを手動で入力するか、\n"
            "証憑管理タブの「レシート管理」からレシートIDを確認してください。"
        )

    def get_expense_data(self) -> Dict[str, Any]:
        """経費データを取得"""
        expense_date = self.date_edit.date().toString("yyyy-MM-dd")
        
        # 勘定科目が空の場合はカテゴリと同じにする
        account_title = self.account_title_edit.text().strip()
        if not account_title:
            account_title = self.category_combo.currentText()
        
        data = {
            "expense_date": expense_date,
            "expense_category": self.category_combo.currentText(),
            "account_title": account_title,
            "store_name": self.store_name_edit.text().strip(),
            "amount": self.amount_spin.value(),
            "quantity": self.quantity_spin.value(),
            "unit_price": self.unit_price_spin.value() if self.unit_price_spin.value() > 0 else None,
            "payment_method": self.payment_method_combo.currentText(),
            "memo": self.memo_edit.toPlainText().strip(),
        }
        
        # レシートIDが入力されている場合
        receipt_id_str = self.receipt_id_edit.text().strip()
        if receipt_id_str:
            # receipt_idからレシートを検索
            receipt = self.receipt_db.find_by_receipt_id(receipt_id_str)
            if receipt:
                data["receipt_id"] = receipt["id"]
                data["receipt_file_path"] = receipt.get("file_path", "")
        
        return data

