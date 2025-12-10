#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
証憑管理ウィジェット

- レシート管理
- 保証書管理
- 経費管理
- 勘定科目設定

※ 以前はフォルダ単位の一括OCRパネルもありましたが、
   現在はシンプルに各機能ごとのタブ構成としています。
"""
from __future__ import annotations

import sys
import os

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ui.receipt_widget import ReceiptWidget
from ui.warranty_widget import WarrantyWidget
from ui.expense_widget import ExpenseWidget
from ui.account_title_widget import AccountTitleWidget


class EvidenceManagerWidget(QWidget):
    """証憑管理タブ（サブタブで各機能を切り替え）"""

    def __init__(self, api_client=None, inventory_widget=None, product_widget=None):
        super().__init__()
        self.api_client = api_client
        self.inventory_widget = inventory_widget
        self.product_widget = product_widget
        self._setup_ui()

    def save_settings(self):
        """このウィジェットに含まれるすべてのサブウィジェットの設定を保存します。"""
        if hasattr(self, 'receipt_widget') and callable(getattr(self.receipt_widget, 'save_settings', None)):
            self.receipt_widget.save_settings()
        if hasattr(self, 'warranty_widget') and callable(getattr(self.warranty_widget, 'save_settings', None)):
            self.warranty_widget.save_settings()
        if hasattr(self, 'expense_widget') and callable(getattr(self.expense_widget, 'save_settings', None)):
            self.expense_widget.save_settings()
        if hasattr(self, 'account_title_widget') and callable(getattr(self.account_title_widget, 'save_settings', None)):
            self.account_title_widget.save_settings()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # レシート管理タブ
        self.receipt_widget = ReceiptWidget(self.api_client, inventory_widget=self.inventory_widget)
        if self.product_widget is not None:
            try:
                self.receipt_widget.set_product_widget(self.product_widget)
            except Exception:
                pass
        self.tab_widget.addTab(self.receipt_widget, "レシート管理")

        # 保証書管理タブ
        self.warranty_widget = WarrantyWidget(self.api_client)
        self.tab_widget.addTab(self.warranty_widget, "保証書管理")

        # 経費管理タブ
        self.expense_widget = ExpenseWidget(self.api_client)
        self.tab_widget.addTab(self.expense_widget, "経費管理")

        # 勘定科目設定タブ
        self.account_title_widget = AccountTitleWidget()
        self.tab_widget.addTab(self.account_title_widget, "勘定科目設定")

