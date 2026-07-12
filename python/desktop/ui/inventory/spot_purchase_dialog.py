#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スポット仕入ルート入力ダイアログ。"""
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

class SpotPurchaseDialog(QDialog):
    """スポット仕入用のルート情報入力ダイアログ（1店舗・スキマ時間仕入対応）
    
    - 日付（ルート日付）
    - 店舗名 / 店舗コード
    - IN / OUT 時刻
    
    を入力してもらい、OK 後にルート登録タブ側で SPOT ルートを作成する。
    """
    
    def __init__(self, store_db, inventory_data: Optional[pd.DataFrame], default_date: Optional[QDate] = None, parent=None):
        super().__init__(parent)
        self.store_db = store_db
        self.inventory_data = inventory_data
        self.default_date = default_date or QDate.currentDate()
        self.stores = []
        self._store_code_by_name = {}
        self.setWindowTitle("スポット仕入 - ルート情報入力")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load_stores()
    
    def _build_ui(self):
        layout = QFormLayout(self)
        # 日付（ルート日付）
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(self.default_date)
        layout.addRow("日付:", self.date_edit)
        # 店舗名（選択で店舗コード自動挿入）
        self.store_combo = QComboBox()
        self.store_combo.setMinimumWidth(280)
        self.store_combo.currentIndexChanged.connect(self._on_store_selected)
        layout.addRow("店舗名:", self.store_combo)
        self.store_code_edit = QLineEdit()
        self.store_code_edit.setReadOnly(True)
        self.store_code_edit.setPlaceholderText("店舗名を選択すると自動で入ります")
        layout.addRow("店舗コード:", self.store_code_edit)
        # IN/OUT時間（HH:mm をキーボードで直接入力）
        now = QTime.currentTime()
        default_time = f"{now.hour():02d}:{now.minute():02d}"
        self.in_time_edit = QLineEdit(default_time)
        self.in_time_edit.setPlaceholderText("例: 10:30")
        self.in_time_edit.setMaximumWidth(80)
        self.in_time_edit.textChanged.connect(self._update_auto_fields)
        layout.addRow("IN時間:", self.in_time_edit)
        self.out_time_edit = QLineEdit(default_time)
        self.out_time_edit.setPlaceholderText("例: 11:45")
        self.out_time_edit.setMaximumWidth(80)
        self.out_time_edit.textChanged.connect(self._update_auto_fields)
        layout.addRow("OUT時間:", self.out_time_edit)
        # 仕入CSVから自動計算される項目（表示用＋微調整可）
        self.stay_minutes_edit = QLineEdit()
        self.stay_minutes_edit.setReadOnly(False)
        self.stay_minutes_edit.setPlaceholderText("IN/OUTから自動計算")
        layout.addRow("滞在(分):", self.stay_minutes_edit)
        self.gross_profit_edit = QLineEdit()
        self.gross_profit_edit.setReadOnly(False)
        self.gross_profit_edit.setPlaceholderText("仕入CSVの見込み利益合計")
        layout.addRow("想定粗利:", self.gross_profit_edit)
        self.item_count_edit = QLineEdit()
        self.item_count_edit.setReadOnly(False)
        self.item_count_edit.setPlaceholderText("仕入点数")
        layout.addRow("仕入れ点数:", self.item_count_edit)
        self.rating_spin = QSpinBox()
        self.rating_spin.setRange(0, 5)
        self.rating_spin.setValue(0)
        layout.addRow("評価(0-5):", self.rating_spin)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)
    
    def _load_stores(self):
        self.stores = self.store_db.list_stores() if self.store_db else []
        self._store_code_by_name.clear()
        self.store_combo.clear()
        self.store_combo.addItem("-- 店舗を選択 --", None)
        for s in self.stores:
            name = s.get("store_name") or ""
            code = s.get("store_code") or s.get("supplier_code") or ""
            if name:
                self.store_combo.addItem(name, code)
                self._store_code_by_name[name] = code
        self.store_code_edit.clear()
    
    def _on_store_selected(self):
        idx = self.store_combo.currentIndex()
        if idx <= 0:
            self.store_code_edit.clear()
            self._update_auto_fields()
            return
        code = self.store_combo.currentData()
        self.store_code_edit.setText(code or "")
        self._update_auto_fields()

    @staticmethod
    def _parse_hhmm(text: str) -> Optional[QTime]:
        """HH:mm または H:mm 形式の時刻文字列を QTime に変換"""
        text = (text or "").strip()
        if not text:
            return None
        parts = text.split(":")
        if len(parts) != 2:
            return None
        try:
            h = int(parts[0])
            m = int(parts[1])
            if 0 <= h < 24 and 0 <= m < 60:
                return QTime(h, m)
        except ValueError:
            return None
        return None
    
    def _update_auto_fields(self):
        """仕入CSVから該当店舗の想定粗利・仕入れ点数を集計し、IN/OUTから滞在(分)を計算"""
        code = self.store_code_edit.text().strip()
        stay_min = 0
        in_t = self._parse_hhmm(self.in_time_edit.text())
        out_t = self._parse_hhmm(self.out_time_edit.text())
        if in_t and out_t:
            in_min = in_t.hour() * 60 + in_t.minute()
            out_min = out_t.hour() * 60 + out_t.minute()
            if out_min >= in_min:
                stay_min = out_min - in_min
            else:
                stay_min = (24 * 60 - in_min) + out_min
        self.stay_minutes_edit.setText(str(stay_min))
        gross = 0
        count = 0
        if code and self.inventory_data is not None and len(self.inventory_data) > 0:
            if "仕入先" in self.inventory_data.columns:
                mask = self.inventory_data["仕入先"].astype(str).str.strip() == code
                subset = self.inventory_data.loc[mask]
                if "見込み利益" in subset.columns:
                    gross = pd.to_numeric(subset["見込み利益"], errors="coerce").fillna(0).sum()
                count = len(subset)
        self.gross_profit_edit.setText(str(int(gross)))
        self.item_count_edit.setText(str(count))
        if count > 0 and gross > 0:
            self.rating_spin.setValue(min(5, max(0, int(gross / 2000) + 1)))
    
    def get_route_date_qdate(self) -> QDate:
        """ユーザーが選択したルート日付を返す"""
        return self.date_edit.date()
    
    def get_in_time_str(self) -> str:
        t = self._parse_hhmm(self.in_time_edit.text())
        if t:
            return f"{t.hour():02d}:{t.minute():02d}"
        return self.in_time_edit.text().strip()
    
    def get_out_time_str(self) -> str:
        t = self._parse_hhmm(self.out_time_edit.text())
        if t:
            return f"{t.hour():02d}:{t.minute():02d}"
        return self.out_time_edit.text().strip()
    
    def accept(self):
        store_name = self.store_combo.currentText().strip()
        if self.store_combo.currentIndex() <= 0 or not store_name or store_name == "-- 店舗を選択 --":
            QMessageBox.warning(self, "入力エラー", "店舗名を選択してください。")
            return
        code = self.store_code_edit.text().strip()
        if not code:
            QMessageBox.warning(self, "入力エラー", "店舗コードが取得できません。")
            return
        if not self._parse_hhmm(self.in_time_edit.text()):
            QMessageBox.warning(
                self, "入力エラー", "IN時間を HH:mm 形式で入力してください。（例: 10:30）"
            )
            return
        if not self._parse_hhmm(self.out_time_edit.text()):
            QMessageBox.warning(
                self, "入力エラー", "OUT時間を HH:mm 形式で入力してください。（例: 11:45）"
            )
            return
        super().accept()
    
    def get_spot_visit(self) -> Dict[str, Any]:
        """ルート情報テーブルに挿入するためのスポット訪問データを返す"""
        store_name = self.store_combo.currentText().strip()
        store_code = self.store_code_edit.text().strip()
        in_str = self.get_in_time_str()
        out_str = self.get_out_time_str()
        try:
            stay_min = int(self.stay_minutes_edit.text() or 0)
        except ValueError:
            stay_min = 0
        return {
            "visit_order": 1,
            "store_code": store_code,
            "store_name": store_name,
            "store_in_time": in_str,
            "store_out_time": out_str,
            "stay_duration": stay_min,
        }

