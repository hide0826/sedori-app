#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""店舗マスタ管理ウィジェット（タブコンテナ・オーケストレーター）。"""
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

from ui.company_master_widget import CompanyMasterWidget
from .store_list import StoreListWidget
from .route_kanban import RouteKanbanWidget
from .online import OnlineStoreListWidget
from .flea_users import FleaMarketUserListWidget
from .expense import ExpenseDestinationListWidget


class StoreMasterWidget(QWidget):
    """店舗マスタ管理ウィジェット（タブコンテナ）"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """UIの設定（タブウィジェット）"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # タブウィジェットの作成
        self.tab_widget = QTabWidget()
        
        # 店舗一覧タブ
        self.store_list_widget = StoreListWidget()
        self.tab_widget.addTab(self.store_list_widget, "店舗一覧")

        # ルート一覧カンバンタブ
        self.route_kanban_widget = RouteKanbanWidget()
        self.tab_widget.addTab(self.route_kanban_widget, "ルート一覧")

        # 電脳店舗タブ
        self.online_store_widget = OnlineStoreListWidget()
        self.tab_widget.addTab(self.online_store_widget, "EC店舗一覧")

        # フリマユーザー一覧タブ（仕入入力の自動補完用マスタ）
        self.flea_market_user_widget = FleaMarketUserListWidget()
        self.tab_widget.addTab(self.flea_market_user_widget, "フリマユーザー一覧")

        # 経費先タブ（店舗一覧と法人マスタの間）
        self.expense_destination_widget = ExpenseDestinationListWidget()
        self.tab_widget.addTab(self.expense_destination_widget, "経費先")
        
        # 法人マスタタブ
        self.company_master_widget = CompanyMasterWidget()
        self.tab_widget.addTab(self.company_master_widget, "法人マスタ")
        
        layout.addWidget(self.tab_widget)

        self._kanban_tab_index = self.tab_widget.indexOf(self.route_kanban_widget)
        self._store_list_dirty = False
        self.route_kanban_widget.routes_changed.connect(self._on_kanban_routes_changed)
        self.store_list_widget.routes_changed.connect(self._on_store_list_routes_changed)
        self.tab_widget.currentChanged.connect(self._on_master_tab_changed)

    def _on_kanban_routes_changed(self) -> None:
        """カンバン操作後に店舗一覧タブのルート情報を同期。

        ルート一覧タブ表示中は店舗テーブルの再読込を後回しにして、戻る等を速くする。
        """
        self.store_list_widget.load_routes()
        if self.tab_widget.currentIndex() == self._kanban_tab_index:
            self._store_list_dirty = True
        else:
            self.store_list_widget.load_stores(self.store_list_widget.search_edit.text())
            self._store_list_dirty = False

    def _on_store_list_routes_changed(self) -> None:
        """店舗一覧のルート編集後にカンバンを同期"""
        self.route_kanban_widget.reload_board()

    def _on_master_tab_changed(self, index: int) -> None:
        """タブ切替時に必要なら最新データを読み込む"""
        if index == self._kanban_tab_index:
            self.route_kanban_widget.reload_board()
        elif index == self.tab_widget.indexOf(self.store_list_widget) and self._store_list_dirty:
            self.store_list_widget.load_stores(self.store_list_widget.search_edit.text())
            self._store_list_dirty = False
