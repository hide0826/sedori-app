#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
経費台帳ウィジェット

経費DBから集計して経費台帳を表示・出力
"""
from __future__ import annotations

import sys
import os
from typing import List, Dict, Any
from datetime import datetime

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QFileDialog, QDateEdit,
)

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.expense_db import ExpenseDatabase
from database.receipt_db import ReceiptDatabase
from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state

import pandas as pd


class ExpenseLedgerWidget(QWidget):
    """経費台帳ウィジェット"""

    def __init__(self, api_client=None):
        super().__init__()
        self.api_client = api_client
        self.expense_db = ExpenseDatabase()
        self.receipt_db = ReceiptDatabase()

        self.setup_ui()
        self.refresh_table()

        # テーブルの列幅を復元
        restore_table_header_state(self.table, "ExpenseLedgerWidget/TableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "ExpenseLedgerWidget/TableState")

    def setup_ui(self) -> None:
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部：ボタンエリア
        button_layout = QHBoxLayout()

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

        button_layout.addStretch()

        # 出力ボタン
        self.export_csv_btn = QPushButton("CSV出力")
        self.export_csv_btn.clicked.connect(self.export_csv)
        button_layout.addWidget(self.export_csv_btn)

        self.export_excel_btn = QPushButton("Excel出力")
        self.export_excel_btn.clicked.connect(self.export_excel)
        button_layout.addWidget(self.export_excel_btn)

        layout.addLayout(button_layout)

        # テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "日付", "勘定科目", "取引先", "金額", "レシートID", "支払方法", "カテゴリ", "メモ",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

    def refresh_table(self) -> None:
        """テーブルを更新"""
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")

        expenses = self.expense_db.list_by_date(start_date=start_date, end_date=end_date)

        self.table.setRowCount(len(expenses))

        for row, expense in enumerate(expenses):
            self.table.setItem(row, 0, QTableWidgetItem(expense.get("expense_date", "")))

            account_title = expense.get("account_title", "") or expense.get("expense_category", "")
            self.table.setItem(row, 1, QTableWidgetItem(account_title))

            self.table.setItem(row, 2, QTableWidgetItem(expense.get("store_name", "")))
            self.table.setItem(row, 3, QTableWidgetItem(str(expense.get("amount", 0))))

            receipt_id = expense.get("receipt_id")
            receipt_id_str = ""
            if receipt_id:
                receipt = self.receipt_db.get_receipt(receipt_id)
                if receipt:
                    receipt_id_str = receipt.get("receipt_id", "")
            self.table.setItem(row, 4, QTableWidgetItem(receipt_id_str))

            self.table.setItem(row, 5, QTableWidgetItem(expense.get("payment_method", "")))
            self.table.setItem(row, 6, QTableWidgetItem(expense.get("expense_category", "")))
            self.table.setItem(row, 7, QTableWidgetItem(expense.get("memo", "")))

    def get_ledger_data(self) -> List[Dict[str, Any]]:
        """台帳データを取得（CSV/Excel出力用）"""
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")

        expenses = self.expense_db.list_by_date(start_date=start_date, end_date=end_date)

        ledger_data: List[Dict[str, Any]] = []
        for expense in expenses:
            receipt_id = expense.get("receipt_id")
            receipt_id_str = ""
            if receipt_id:
                receipt = self.receipt_db.get_receipt(receipt_id)
                if receipt:
                    receipt_id_str = receipt.get("receipt_id", "")

            account_title = expense.get("account_title", "") or expense.get("expense_category", "")

            ledger_data.append(
                {
                    "日付": expense.get("expense_date", ""),
                    "勘定科目": account_title,
                    "取引先": expense.get("store_name", ""),
                    "金額": expense.get("amount", 0),
                    "摘要": expense.get("expense_category", ""),
                    "レシートID": receipt_id_str,
                    "支払方法": expense.get("payment_method", ""),
                    "メモ": expense.get("memo", ""),
                }
            )

        return ledger_data

    def export_csv(self) -> None:
        """CSV形式で出力"""
        ledger_data = self.get_ledger_data()
        if not ledger_data:
            QMessageBox.warning(self, "警告", "出力するデータがありません。")
            return

        default_filename = f"経費台帳_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "経費台帳をCSV形式で保存",
            default_filename,
            "CSVファイル (*.csv);;すべてのファイル (*)",
        )

        if not file_path:
            return

        try:
            df = pd.DataFrame(ledger_data)
            columns = ["日付", "勘定科目", "取引先", "金額", "摘要", "レシートID", "支払方法", "メモ"]
            available_columns = [col for col in columns if col in df.columns]
            df = df[available_columns]

            df.to_csv(file_path, index=False, encoding="cp932", errors="replace")

            QMessageBox.information(self, "完了", f"経費台帳をCSV形式で保存しました:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"CSV出力に失敗しました:\n{e}")

    def export_excel(self) -> None:
        """Excel形式で出力"""
        ledger_data = self.get_ledger_data()
        if not ledger_data:
            QMessageBox.warning(self, "警告", "出力するデータがありません。")
            return

        default_filename = f"経費台帳_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "経費台帳をExcel形式で保存",
            default_filename,
            "Excelファイル (*.xlsx);;すべてのファイル (*)",
        )

        if not file_path:
            return

        try:
            df = pd.DataFrame(ledger_data)
            columns = ["日付", "勘定科目", "取引先", "金額", "摘要", "レシートID", "支払方法", "メモ"]
            available_columns = [col for col in columns if col in df.columns]
            df = df[available_columns]

            df.to_excel(file_path, index=False, engine="openpyxl")

            QMessageBox.information(self, "完了", f"経費台帳をExcel形式で保存しました:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"Excel出力に失敗しました:\n{e}")

