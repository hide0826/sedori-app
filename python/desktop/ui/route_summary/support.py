#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_summary 共通定数・ヘルパー・ダイアログ。"""
from __future__ import annotations

from typing import Optional, Dict, Any, List, Tuple
import html
import os
import sys
import re
import logging
import webbrowser
from functools import partial
from datetime import datetime, time as dt_time
from pathlib import Path

import pandas as pd
import openpyxl

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QFileDialog, QDateTimeEdit, QLineEdit,
    QTextEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QDialog, QFormLayout, QDialogButtonBox, QTabWidget, QStyledItemDelegate, QStyle, QInputDialog,
    QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QDateTime, QTime, Signal, QSettings, QUrl
from PySide6.QtGui import QColor, QShortcut, QKeySequence, QDrag, QGuiApplication, QBrush

from ui.star_rating_widget import StarRatingWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    QWebEngineView = None  # type: ignore
    WEBENGINE_AVAILABLE = False

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from database.route_db import RouteDatabase
from database.store_db import StoreDatabase
from database.route_visit_db import RouteVisitDatabase

try:
    from utils.ui_utils import attach_table_column_width_persistence, reapply_table_column_widths
except ImportError:
    from desktop.utils.ui_utils import (  # type: ignore
        attach_table_column_width_persistence,
        reapply_table_column_widths,
    )

try:
    from services.route_matching_service import RouteMatchingService
except ImportError:
    try:
        from desktop.services.route_matching_service import RouteMatchingService  # type: ignore
    except ImportError:
        RouteMatchingService = None

try:
    from services.calculation_service import CalculationService
except ImportError:
    try:
        from desktop.services.calculation_service import CalculationService  # type: ignore
    except ImportError:
        CalculationService = None

try:
    from utils.template_generator import TemplateGenerator
except ImportError:
    try:
        from desktop.utils.template_generator import TemplateGenerator  # type: ignore
    except ImportError:
        TemplateGenerator = None

try:
    from services.google_maps_route_url_service import generate_route_map_urls
except ImportError:
    try:
        from desktop.services.google_maps_route_url_service import generate_route_map_urls  # type: ignore
    except ImportError:
        generate_route_map_urls = None

try:
    from services.google_maps_service import resolve_maps_api_key
except ImportError:
    try:
        from desktop.services.google_maps_service import resolve_maps_api_key  # type: ignore
    except ImportError:
        resolve_maps_api_key = None

# 分割ルートごとの行背景色（ダークテーマ向け・半透明）
ROUTE_SEGMENT_ROW_COLORS = [
    QColor(90, 162, 255, 55),   # ルート1: 青
    QColor(40, 167, 69, 60),    # ルート2: 緑
    QColor(255, 193, 7, 55),    # ルート3: 黄
    QColor(220, 53, 69, 50),    # ルート4: 赤
]

# 店舗訪問詳細テーブル列インデックス
COL_VISIT_INCLUDE = 0   # テンプレート出力チェック
COL_VISIT_ORDER = 1
COL_STORE_CODE = 2
COL_STORE_NAME = 3
COL_IN_TIME = 4
COL_OUT_TIME = 5
COL_STAY = 6
COL_TRAVEL = 7
COL_PROFIT = 8
COL_QTY = 9
COL_STAR = 10
COL_NOTES = 11

# テンプレート生成向けに表示する列（それ以外は非表示だがデータは保持）
VISIT_TABLE_VISIBLE_COLUMNS = {
    COL_VISIT_INCLUDE,
    COL_VISIT_ORDER,
    COL_STORE_CODE,
    COL_STORE_NAME,
    COL_NOTES,
}

# ルート選択タブ用ワークフロー手順（①〜⑤）
_ROUTE_WORKFLOW_PIPELINE_SEGMENTS = [
    "①ルート日付選択",
    "②ルートコード選択",
    "③選択ルート読込（ボタン）",
    "④地図エリアの再読込（ボタン）",
    "⑤テンプレート生成",
]
_ROUTE_WORKFLOW_PIPELINE_SEP = "\u2010"

# 店舗訪問詳細テーブル: 列幅の初期値（12列・未保存時のみ使用）
_VISIT_TABLE_DEFAULT_WIDTHS = [
    52, 72, 100, 200, 80, 80, 80, 80, 80, 72, 100, 180,
]



def _format_route_workflow_prefix_html(text: str, emphasize: bool) -> str:
    """ワークフロー行の左側（手順リストより前）。"""
    if not emphasize:
        return f'<span style="color:#cccccc;">{html.escape(text)}</span>'
    t = text.strip()
    if t == "ワークフロー: 実行中":
        return (
            '<span style="color:#cccccc;">ワークフロー: </span>'
            '<span style="color:#ffd54f;font-weight:600;">実行中</span>'
        )
    return f'<span style="color:#ffd54f;font-weight:600;">{html.escape(text)}</span>'


def _format_route_workflow_pipeline_html(active_step: Optional[int]) -> str:
    parts: List[str] = []
    for i, seg in enumerate(_ROUTE_WORKFLOW_PIPELINE_SEGMENTS, start=1):
        esc = html.escape(seg)
        if active_step == i:
            parts.append(f'<span style="color:#ffd54f;font-weight:600;">{esc}</span>')
        else:
            parts.append(f'<span style="color:#9e9e9e;">{esc}</span>')
    return _ROUTE_WORKFLOW_PIPELINE_SEP.join(parts)


def _template_include_from_db_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _visit_include_checked(table: QTableWidget, row: int) -> bool:
    widget = table.cellWidget(row, COL_VISIT_INCLUDE)
    if widget is None:
        return True
    checkbox = widget.findChild(QCheckBox)
    return checkbox.isChecked() if checkbox else True


class SafeInternalMoveTable(QTableWidget):
    """セルウィジェットを含む行を安全に並び替えるためのテーブル。"""

    rows_reordered = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drag_source_row: Optional[int] = None

    def startDrag(self, supportedActions) -> None:
        # dropEvent 時点の currentRow() は移動先に変わる場合があるため、
        # ドラッグ開始時の行を保持しておく。
        self._drag_source_row = self.currentRow()
        if self._drag_source_row < 0:
            return
        indexes = self.selectedIndexes()
        if not indexes:
            return
        mime = self.model().mimeData(indexes)
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        # QAbstractItemView の標準 startDrag は MoveAction 後に削除処理を行う場合があるため、
        # ここでは独自に drag を実行して二重削除を防ぐ。
        drag.exec(Qt.MoveAction)

    def _clone_row(self, row: int) -> Dict[str, Any]:
        texts: List[str] = []
        for col in range(self.columnCount()):
            if col in (COL_VISIT_INCLUDE, COL_STAR):
                texts.append("")
            else:
                item = self.item(row, col)
                texts.append(item.text() if item is not None else "")
        include_checked = _visit_include_checked(self, row)
        star_rating = 0.0
        star_widget = self.cellWidget(row, COL_STAR)
        if isinstance(star_widget, StarRatingWidget):
            star_rating = float(star_widget.rating())
        return {"texts": texts, "star_rating": star_rating, "include_checked": include_checked}

    def _restore_row(self, row: int, payload: Dict[str, Any]) -> None:
        texts = payload.get("texts", [])
        for col, text in enumerate(texts):
            if col in (COL_VISIT_INCLUDE, COL_STAR):
                continue
            self.setItem(row, col, QTableWidgetItem(str(text)))
        include_checked = payload.get("include_checked", True)
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        checkbox = QCheckBox(container)
        checkbox.setChecked(bool(include_checked))
        layout.addWidget(checkbox)
        self.setCellWidget(row, COL_VISIT_INCLUDE, container)
        star_widget = StarRatingWidget(self, rating=float(payload.get("star_rating", 0.0)), star_size=14)
        self.setCellWidget(row, COL_STAR, star_widget)

    def dropEvent(self, event) -> None:
        if event.source() is not self:
            super().dropEvent(event)
            return

        src_row = self._drag_source_row if self._drag_source_row is not None else self.currentRow()
        self._drag_source_row = None
        if src_row < 0:
            event.ignore()
            return

        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        dst_row = self.rowAt(pos.y())
        if dst_row < 0:
            dst_row = self.rowCount() - 1

        # 同じ場所へのドロップは何もしない
        if dst_row in (src_row, src_row + 1):
            event.ignore()
            return

        payload = self._clone_row(src_row)

        self.blockSignals(True)
        try:
            dst_row = max(0, min(dst_row, self.rowCount() - 1))
            if dst_row > src_row:
                # 下方向へ移動: 間の行を上へ詰める
                for r in range(src_row, dst_row):
                    self._restore_row(r, self._clone_row(r + 1))
            else:
                # 上方向へ移動: 間の行を下へずらす
                for r in range(src_row, dst_row, -1):
                    self._restore_row(r, self._clone_row(r - 1))
            self._restore_row(dst_row, payload)
        finally:
            self.blockSignals(False)

        self.selectRow(dst_row)
        event.acceptProposedAction()
        self.rows_reordered.emit()


class StoreSelectDialog(QDialog):
    """店舗マスタ一覧を表示して選択させるダイアログ"""
    def __init__(self, store_db: StoreDatabase, parent=None):
        super().__init__(parent)
        self.setWindowTitle("店舗マスタから追加")
        self.resize(700, 480)
        self.store_db = store_db
        self.selected_rows: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("コード/店舗名で検索")
        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self.filter_rows)
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["ルート名", "店舗コード", "店舗名"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.load_rows()

    def load_rows(self):
        try:
            stores = self.store_db.list_stores()
        except Exception:
            stores = []
        self.all_rows = stores
        self.populate(stores)

    def populate(self, stores: List[Dict[str, Any]]):
        self.table.setRowCount(len(stores))
        for i, s in enumerate(stores):
            self.table.setItem(i, 0, QTableWidgetItem(str(s.get('affiliated_route_name', ''))))
            self.table.setItem(i, 1, QTableWidgetItem(str(s.get('supplier_code', ''))))
            self.table.setItem(i, 2, QTableWidgetItem(str(s.get('store_name', ''))))

    def filter_rows(self):
        q = self.search_edit.text().strip().lower()
        if not q:
            self.populate(self.all_rows)
            return
        filtered = [s for s in self.all_rows if q in str(s.get('supplier_code','')).lower() or q in str(s.get('store_name','')).lower()]
        self.populate(filtered)

    def get_selected_stores(self) -> List[Dict[str, Any]]:
        rows = []
        for idx in self.table.selectionModel().selectedRows():
            r = idx.row()
            code = self.table.item(r, 1).text() if self.table.item(r, 1) else ''
            name = self.table.item(r, 2).text() if self.table.item(r, 2) else ''
            route = self.table.item(r, 0).text() if self.table.item(r, 0) else ''
            rows.append({'supplier_code': code, 'store_name': name, 'affiliated_route_name': route})
        return rows


class SavedRoutesDialog(QDialog):
    """保存済みルートの一覧から選択して読込/削除するダイアログ"""
    def __init__(self, route_db: RouteDatabase, store_db: StoreDatabase, parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存履歴")
        self.resize(720, 420)
        self.route_db = route_db
        self.store_db = store_db
        self._result_action = None  # 'load' or 'delete'
        self._result_id = None

        layout = QVBoxLayout(self)

        # フィルタ行（デフォルトは全件表示。必要時のみチェックして絞り込む）
        filt = QHBoxLayout()
        from PySide6.QtWidgets import QDateEdit
        self.chk_date = QCheckBox("仕入れ日")
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDateTime(QDateTime.currentDateTime())
        self.chk_route = QCheckBox("ルート名")
        self.route_combo = QComboBox()
        self.route_combo.setEditable(True)
        try:
            names = self.store_db.get_route_names()
            for n in names:
                self.route_combo.addItem(n)
        except Exception:
            pass
        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self._reload)
        filt.addWidget(self.chk_date)
        filt.addWidget(self.date_edit)
        filt.addWidget(self.chk_route)
        filt.addWidget(self.route_combo)
        filt.addWidget(search_btn)
        layout.addLayout(filt)

        # 一覧テーブル
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "仕入れ日", "ルートコード（ルート名）", "最終更新"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        # 列幅を内容に合わせて自動調整（最終更新列が切れないように）
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)

        # ボタン
        btns = QDialogButtonBox()
        self.load_btn = QPushButton("読み込み")
        self.del_btn = QPushButton("削除")
        self.cancel_btn = QPushButton("閉じる")
        btns.addButton(self.load_btn, QDialogButtonBox.AcceptRole)
        btns.addButton(self.del_btn, QDialogButtonBox.ActionRole)
        btns.addButton(self.cancel_btn, QDialogButtonBox.RejectRole)
        layout.addWidget(btns)

        self.load_btn.clicked.connect(self._on_load)
        self.del_btn.clicked.connect(self._on_delete)
        self.cancel_btn.clicked.connect(self.reject)

        self._reload()

    def _reload(self):
        try:
            route_name = self.route_combo.currentText().strip()
            route_code = None
            if self.chk_route.isChecked() and route_name:
                route_code = self.store_db.get_route_code_by_name(route_name)
        except Exception:
            route_code = None
        if self.chk_date.isChecked():
            day = self.date_edit.date().toString('yyyy-MM-dd')
            start = day; end = day
        else:
            start = None; end = None
        rows = self.route_db.list_route_summaries(start_date=start, end_date=end, route_code=route_code)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rid = str(r.get('id',''))
            rdate = str(r.get('route_date',''))
            rcode = str(r.get('route_code',''))
            # ルート名に変換
            try:
                rname = self.store_db.get_route_name_by_code(rcode) or ''
            except Exception:
                rname = ''
            code_display = f"{rcode}"
            if rname:
                code_display = f"{rcode}（{rname}）"
            updated_at = str(r.get('updated_at',''))

            self.table.setItem(i, 0, QTableWidgetItem(rid))
            self.table.setItem(i, 1, QTableWidgetItem(rdate))
            self.table.setItem(i, 2, QTableWidgetItem(code_display))
            self.table.setItem(i, 3, QTableWidgetItem(updated_at))
        # データ投入後に列幅を最適化
        try:
            self.table.resizeColumnsToContents()
        except Exception:
            pass

    def _selected_id(self) -> Optional[int]:
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
        rid = self._selected_id()
        if rid is None:
            QMessageBox.information(self, "情報", "読み込む行を選択してください")
            return
        self._result_action = 'load'
        self._result_id = rid
        self.accept()

    def _on_delete(self):
        rid = self._selected_id()
        if rid is None:
            QMessageBox.information(self, "情報", "削除する行を選択してください")
            return
        self._result_action = 'delete'
        self._result_id = rid
        self.accept()

    def get_result(self):
        return self._result_action, self._result_id

