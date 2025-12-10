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
    QLineEdit,
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

        # テーブルの列幅を復元
        restore_table_header_state(self.table, "AccountTitleWidget/TableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "AccountTitleWidget/TableState")

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
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

