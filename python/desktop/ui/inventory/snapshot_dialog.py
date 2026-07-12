#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""統合スナップショット選択ダイアログ。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QSplitter, QMessageBox, QFrame,
    QCheckBox, QSpinBox, QDateEdit, QFileDialog,
    QDialog, QDialogButtonBox, QSizePolicy, QInputDialog, QProgressDialog,
    QPlainTextEdit, QScrollArea, QFormLayout,
    QToolButton, QApplication, QAbstractItemView,
)
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, Signal, QSettings, QThread, QTimer
from PySide6.QtGui import QFont, QColor, QPalette, QStandardItemModel, QStandardItem, QDesktopServices
from PySide6.QtCore import QUrl
import pandas as pd
from pathlib import Path
import re
import sys
import os
import tempfile
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime
from html import escape

# ui/inventory/ から desktop/ を import パス先頭へ
_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)


from database.store_db import StoreDatabase
from database.inventory_db import InventoryDatabase
from database.inventory_route_snapshot_db import InventoryRouteSnapshotDatabase
from database.product_db import ProductDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from database.route_visit_db import RouteVisitDatabase
from database.warranty_db import WarrantyDatabase
from ui.star_rating_widget import StarRatingWidget
try:
    from utils.route_utils import mark_route_flags_from_folder
    from utils.settings_helper import (
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
    )
except ImportError:
    from desktop.utils.route_utils import mark_route_flags_from_folder  # type: ignore
    from desktop.utils.settings_helper import (  # type: ignore
        get_pricetar_listing_url,
        is_pro_enabled,
        is_recording_mode,
    )

try:
    from ui.utils.draggable_file_icon import DraggableFileIconWidget
except ImportError:
    from desktop.ui.utils.draggable_file_icon import DraggableFileIconWidget  # type: ignore

try:
    from ui.utils.browser_front_scheduler import schedule_bring_browser_to_front
except ImportError:
    from desktop.ui.utils.browser_front_scheduler import schedule_bring_browser_to_front  # type: ignore

from services.keepa_service import KeepaService
from services.ocr_service import OCRService
from services.purchase_cost_calc import (
    COL_PLATFORM_FEE,
    COL_SHIPPING,
    COL_TOTAL_COST,
    COL_LEGACY_AMAZON_FEE,
    augment_purchase_cost_record,
    backfill_total_cost_dataframe,
    cell_has_numeric_value,
    fee_storage_value,
    format_money_display,
    is_fee_amount_column,
    migrate_dataframe_fee_columns,
    read_fee_fields,
    recalculate_profit_fields,
    sync_total_cost_field,
    to_float as purchase_cost_to_float,
)

from .support import (
    SALES_CHANNEL_OPTIONS,
    SHIPPING_METHOD_OPTIONS,
    _ConditionNoteAiGenerateThread,
    _normalize_condition_note_newlines,
    _to_stored_newlines,
    _is_repricing_enabled_value,
)

class CombinedSnapshotDialog(QDialog):
    """統合スナップショットの一覧から選択して読込するダイアログ"""
    
    def __init__(self, route_snapshot_db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("統合スナップショット読込")
        self.resize(720, 420)
        self.route_snapshot_db = route_snapshot_db
        self._selected_snapshot_id = None
        
        layout = QVBoxLayout(self)
        
        # 説明ラベル
        info_label = QLabel("読み込むスナップショットを選択してください:")
        layout.addWidget(info_label)
        
        # 一覧テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["ID", "保存名", "作成日時"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)
        
        # ボタン
        btns = QDialogButtonBox()
        self.load_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        btns.addButton(self.load_btn, QDialogButtonBox.AcceptRole)
        btns.addButton(self.cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(btns)
        
        self.load_btn.clicked.connect(self._on_load)
        self.cancel_btn.clicked.connect(self.reject)
        
        self._reload()
    
    def _reload(self):
        """一覧を再読み込み"""
        try:
            snapshots = self.route_snapshot_db.list_snapshots()
            
            self.table.setRowCount(len(snapshots))
            for i, snap in enumerate(snapshots):
                snapshot_id = str(snap.get('id', ''))
                snapshot_name = str(snap.get('snapshot_name', ''))
                created_at = str(snap.get('created_at', ''))
                
                self.table.setItem(i, 0, QTableWidgetItem(snapshot_id))
                self.table.setItem(i, 1, QTableWidgetItem(snapshot_name))
                self.table.setItem(i, 2, QTableWidgetItem(created_at))
            
            self.table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"一覧の読み込みに失敗しました:\n{str(e)}")
    
    def _selected_id(self):
        """選択されている行のIDを取得"""
        sel = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not sel:
            return None
        r = sel[0].row()
        item = self.table.item(r, 0)
        try:
            return int(item.text()) if item else None
        except Exception:
            return None
    
    def _on_load(self):
        """読み込みボタンクリック"""
        snapshot_id = self._selected_id()
        if snapshot_id is None:
            QMessageBox.information(self, "情報", "読み込むスナップショットを選択してください")
            return
        self._selected_snapshot_id = snapshot_id
        self.accept()
    
    def get_selected_snapshot_id(self):
        """選択されたスナップショットIDを取得"""
        return self._selected_snapshot_id

