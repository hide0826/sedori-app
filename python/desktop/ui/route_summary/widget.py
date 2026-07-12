#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ルートサマリー入力ウィジェット（オーケストレーター）。"""
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

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from .support import (
    WEBENGINE_AVAILABLE,
    QWebEngineView,
    ROUTE_SEGMENT_ROW_COLORS,
    COL_VISIT_INCLUDE,
    COL_VISIT_ORDER,
    COL_STORE_CODE,
    COL_STORE_NAME,
    COL_IN_TIME,
    COL_OUT_TIME,
    COL_STAY,
    COL_TRAVEL,
    COL_PROFIT,
    COL_QTY,
    COL_STAR,
    COL_NOTES,
    VISIT_TABLE_VISIBLE_COLUMNS,
    _VISIT_TABLE_DEFAULT_WIDTHS,
    _format_route_workflow_prefix_html,
    _format_route_workflow_pipeline_html,
    _template_include_from_db_value,
    _visit_include_checked,
    SafeInternalMoveTable,
    StoreSelectDialog,
    SavedRoutesDialog,
    RouteDatabase,
    StoreDatabase,
    RouteVisitDatabase,
    attach_table_column_width_persistence,
    reapply_table_column_widths,
    RouteMatchingService,
    CalculationService,
    TemplateGenerator,
    generate_route_map_urls,
    resolve_maps_api_key,
)
from .workflow_mixin import RouteSummaryWorkflowMixin
from .map_mixin import RouteSummaryMapMixin
from .visit_table_mixin import RouteSummaryVisitTableMixin
from .template_mixin import RouteSummaryTemplateMixin
from .matching_mixin import RouteSummaryMatchingMixin
from .persistence_mixin import RouteSummaryPersistenceMixin
from .calc_mixin import RouteSummaryCalcMixin

class RouteSummaryWidget(
    RouteSummaryWorkflowMixin,
    RouteSummaryMapMixin,
    RouteSummaryVisitTableMixin,
    RouteSummaryTemplateMixin,
    RouteSummaryMatchingMixin,
    RouteSummaryPersistenceMixin,
    RouteSummaryCalcMixin,
    QWidget,
):
    """ルートサマリー入力ウィジェット"""

    data_saved = Signal(int)  # データ保存完了

    def __init__(self, api_client=None, inventory_widget=None):
        super().__init__()
        self.route_db = RouteDatabase()
        self.store_db = StoreDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.matching_service = RouteMatchingService() if RouteMatchingService else None
        self.calc_service = CalculationService() if CalculationService else None
        self.api_client = api_client
        # 本番用・開発用それぞれの仕入管理ウィジェットを保持
        self.inventory_widget_main = None
        self.inventory_widget_dev = None
        self.inventory_widget = None  # 従来コードとの互換用（主に本番タブを指す）
        if inventory_widget is not None:
            if getattr(inventory_widget, "dev_mode", False):
                self.inventory_widget_dev = inventory_widget
            else:
                self.inventory_widget_main = inventory_widget
        # 互換用ポインタ（本番→開発の優先順で設定）
        self.inventory_widget = self.inventory_widget_main or self.inventory_widget_dev
        
        self.current_route_id = None
        self.route_data = {}
        self.store_visits = []
        self.latest_summary_metrics = {}
        self.settings = QSettings("HIRIO", "SedoriDesktopApp")
        self.last_loaded_template_path: str = ""
        # テンプレート生成のデフォルトフォルダ
        stored_template_dir = self.settings.value("route_template/default_save_dir", "")
        self.template_save_default_dir = str(stored_template_dir) if stored_template_dir else ""
        
        # Undo/Redoスタック
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_history = 50  # 最大履歴数
        self._is_reordering_rows = False
        self._map_route_segments = []
        self._last_store_code_to_segment: Dict[str, int] = {}
        self._pending_map_segment = None
        self._last_load_was_embed = False
        self._embed_error_notified = False
        self.map_view = None
        
        self.setup_ui()

    def _close_db_connection(self, db) -> None:
        if db is None:
            return
        conn = getattr(db, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            db.conn = None

    def reinit_databases(self) -> None:
        """デモモード切替後にDB接続を差し替える。"""
        for attr in ("route_db", "store_db", "route_visit_db"):
            self._close_db_connection(getattr(self, attr, None))
        self.route_db = RouteDatabase()
        self.store_db = StoreDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.current_route_id = None
        self.route_data = {}
        self.store_visits = []

    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 中央：ルート情報・地図・店舗訪問詳細
        self.setup_tabs(layout)
        
        # 下部：計算結果表示
        self.setup_calculation_results(layout)

    def create_action_button_group(self) -> QGroupBox:
        """操作ボタングループを作成"""
        button_group = QGroupBox("操作")
        button_layout = QHBoxLayout(button_group)
        
        self.template_btn = QPushButton("テンプレート生成")
        self.template_btn.clicked.connect(
            lambda: self._run_workflow_action(5, self.generate_template)
        )
        self.template_btn.setStyleSheet("background-color: #28a745; color: white;")
        button_layout.addWidget(self.template_btn)

        self.load_route_btn = QPushButton("選択ルート読み込み")
        self.load_route_btn.clicked.connect(
            lambda: self._run_workflow_action(3, self.auto_add_stores)
        )
        self.load_route_btn.setStyleSheet("background-color: #17a2b8; color: white;")
        button_layout.addWidget(self.load_route_btn)
        
        button_layout.addStretch()
        
        self.template_root_btn = QPushButton("デフォルト設定")
        self.template_root_btn.setToolTip("ルートテンプレートを保存する起点フォルダを設定します。")
        self.template_root_btn.clicked.connect(self.set_template_root_directory)
        button_layout.addWidget(self.template_root_btn)
        
        return button_group

    def setup_tabs(self, parent_layout):
        """タブの設定（統合版）"""
        # 単一のウィジェットに統合
        unified_widget = self.create_unified_widget()
        parent_layout.addWidget(unified_widget)

    def create_unified_widget(self) -> QWidget:
        """ルート情報・店舗訪問詳細（左）と地図（右）を統合したウィジェット"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        main_splitter = QSplitter(Qt.Horizontal)

        # ── 左パネル: 操作 + ルート情報 + 店舗訪問詳細 ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.create_action_button_group())

        self.visit_order_hint_label = QLabel(
            "店舗訪問順序はドラッグ＆ドロップで変更出来ます。"
            "訪問順序を変更した場合は訪問順序保存ボタンを押してください。"
        )
        self.visit_order_hint_label.setWordWrap(True)
        self.visit_order_hint_label.setStyleSheet("color: #cccccc; padding: 2px 0px;")
        left_layout.addWidget(self.visit_order_hint_label)

        self._workflow_status_text = "ワークフロー: 未実行"
        self._workflow_emphasize = False
        self._workflow_active_step: Optional[int] = None
        self.workflow_guide_label = QLabel()
        self.workflow_guide_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_guide_label.setWordWrap(True)
        self.workflow_guide_label.setStyleSheet("padding: 2px 0px;")
        self._sync_workflow_guide_label()
        left_layout.addWidget(self.workflow_guide_label)

        route_group = QGroupBox("ルート情報")
        route_layout = QFormLayout(route_group)
        route_layout.setSpacing(6)

        self.route_date_edit = QDateTimeEdit()
        self.route_date_edit.setCalendarPopup(True)
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.route_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.route_date_edit.dateChanged.connect(
            lambda _date: self._set_workflow_pipeline_highlight(1)
        )
        route_layout.addRow("ルート日付:", self.route_date_edit)

        self.route_code_combo = QComboBox()
        self.route_code_combo.setEditable(True)
        self.route_code_combo.currentTextChanged.connect(self.on_route_code_changed)
        self.route_code_combo.currentTextChanged.connect(
            lambda text: self._set_workflow_pipeline_highlight(2) if str(text).strip() else None
        )
        route_layout.addRow("ルートコード:", self.route_code_combo)
        self.route_code_combo.blockSignals(True)
        self.update_route_codes()
        self.route_code_combo.setCurrentText("")
        self.route_code_combo.blockSignals(False)

        url1_widget, self.route_url_1_edit = self._create_route_url_row("再読込で生成されます")
        route_layout.addRow("生成ルート URL 1:", url1_widget)
        url2_widget, self.route_url_2_edit = self._create_route_url_row("2本目がある場合に表示")
        route_layout.addRow("生成ルート URL 2:", url2_widget)

        left_layout.addWidget(route_group)

        visits_group = QGroupBox("店舗訪問詳細")
        visits_layout = QVBoxLayout(visits_group)

        self.route_segment_legend = QLabel("")
        self.route_segment_legend.setStyleSheet("color: #adb5bd; font-size: 11px; padding: 0 4px;")
        visits_layout.addWidget(self.route_segment_legend)

        self.store_visits_table = SafeInternalMoveTable()
        self.store_visits_table.setAlternatingRowColors(True)
        self.store_visits_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.store_visits_table.setSelectionMode(QTableWidget.SingleSelection)
        self.store_visits_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.store_visits_table.setTextElideMode(Qt.ElideNone)
        self.store_visits_table.setWordWrap(True)
        self.store_visits_table.setDragEnabled(True)
        self.store_visits_table.setAcceptDrops(True)
        self.store_visits_table.setDropIndicatorShown(True)
        self.store_visits_table.setDragDropMode(QTableWidget.InternalMove)
        self.store_visits_table.setDragDropOverwriteMode(False)
        try:
            from PySide6.QtWidgets import QAbstractItemView
            self.store_visits_table.setAutoScroll(False)
            self.store_visits_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        except Exception:
            pass
        self.store_visits_table.setDefaultDropAction(Qt.MoveAction)

        headers = [
            "出力", "訪問順序", "店舗コード", "店舗名", "店舗IN時間", "店舗OUT時間",
            "店舗滞在時間", "移動時間（分）", "想定粗利", "仕入れ点数",
            "店舗評価", "備考"
        ]
        self.store_visits_table.setColumnCount(len(headers))
        self.store_visits_table.setHorizontalHeaderLabels(headers)

        header = self.store_visits_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        try:
            header.setSectionsMovable(False)
        except Exception:
            pass
        try:
            self.store_visits_table.verticalHeader().setSectionsMovable(False)
        except Exception:
            pass

        self._apply_visit_table_column_visibility()
        self._setup_visit_table_column_persistence()

        self.store_visits_table.verticalHeader().setDefaultSectionSize(24)
        self.store_visits_table.rows_reordered.connect(self.on_rows_reordered_safe)
        self.store_visits_table.itemChanged.connect(self.on_table_item_changed)
        self.setup_shortcuts()

        class MinimalFocusDelegate(QStyledItemDelegate):
            def paint(self, painter, option, index):
                if option.state & QStyle.State_HasFocus:
                    option.state &= ~QStyle.State_HasFocus
                if option.state & QStyle.State_Selected:
                    option.state &= ~QStyle.State_Selected
                super().paint(painter, option, index)

            def createEditor(self, parent, option, index):
                from PySide6.QtWidgets import QLineEdit
                editor = QLineEdit(parent)
                editor.setFrame(False)
                editor.setStyleSheet(
                    "QLineEdit{"
                    "background-color: #2b2b2b;"
                    "color: #ffffff;"
                    "border: 1px solid #5aa2ff;"
                    "border-radius: 3px;"
                    "padding: 2px 6px;"
                    "}"
                )
                try:
                    editor.setAutoFillBackground(True)
                except Exception:
                    pass
                try:
                    editor.setTextMargins(4, 0, 4, 0)
                except Exception:
                    pass
                return editor

        self.store_visits_table.setItemDelegateForColumn(COL_NOTES, MinimalFocusDelegate(self.store_visits_table))
        self.store_visits_table.setStyleSheet(
            "QTableView::item:focus{outline: none;}"
            "QTableView::item:selected{background-color: rgba(90,162,255,0.18); color: #ffffff; border: none;}"
            "QTableView::item{border: none;}"
        )

        visits_layout.addWidget(self.store_visits_table)

        button_layout = QHBoxLayout()
        add_from_master_btn = QPushButton("店舗追加")
        add_from_master_btn.setToolTip("店舗マスタから追加")
        add_from_master_btn.clicked.connect(self.add_store_from_master)
        button_layout.addWidget(add_from_master_btn)
        add_row_btn = QPushButton("行追加")
        add_row_btn.clicked.connect(self.add_store_visit_row)
        button_layout.addWidget(add_row_btn)
        delete_row_btn = QPushButton("行削除")
        delete_row_btn.clicked.connect(self.delete_store_visit_row)
        button_layout.addWidget(delete_row_btn)
        clear_all_btn = QPushButton("全行クリア")
        clear_all_btn.clicked.connect(self.clear_all_rows)
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        button_layout.addWidget(clear_all_btn)
        reorder_btn = QPushButton("一括入替")
        reorder_btn.clicked.connect(self.reorder_by_visit_order)
        reorder_btn.setToolTip("訪問順序列の数字で並び替え")
        reorder_btn.setStyleSheet("background-color: #17a2b8; color: white;")
        button_layout.addWidget(reorder_btn)
        save_order_btn = QPushButton("訪問順序保存")
        save_order_btn.clicked.connect(self.save_visit_order_to_db)
        save_order_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        button_layout.addWidget(save_order_btn)
        button_layout.addStretch()
        undo_btn = QPushButton("元に戻す")
        undo_btn.clicked.connect(self.undo_action)
        undo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(undo_btn)
        redo_btn = QPushButton("やり直す")
        redo_btn.clicked.connect(self.redo_action)
        redo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(redo_btn)
        visits_layout.addLayout(button_layout)

        left_layout.addWidget(visits_group, 1)

        map_group = self._create_map_panel()

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(map_group)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setSizes([480, 720])

        layout.addWidget(main_splitter, 1)

        try:
            self.save_table_state()
        except Exception:
            pass
        return widget

    def showEvent(self, event):
        """ウィジェットが表示されたときにルートコード一覧を更新"""
        super().showEvent(event)
        # ルートコード一覧を最新の状態に更新
        if hasattr(self, 'route_code_combo') and self.route_code_combo:
            self.update_route_codes()

    def create_route_info_widget(self) -> QWidget:
        """ルート情報入力ウィジェットの作成"""
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setSpacing(10)
        
        # ルート日付
        self.route_date_edit = QDateTimeEdit()
        self.route_date_edit.setCalendarPopup(True)
        self.route_date_edit.setDateTime(QDateTime.currentDateTime())
        self.route_date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addRow("ルート日付:", self.route_date_edit)
        
        # ルートコード（プルダウン）
        self.route_code_combo = QComboBox()
        self.route_code_combo.setEditable(True)  # 手動入力も可能
        self.route_code_combo.currentTextChanged.connect(self.on_route_code_changed)
        layout.addRow("ルートコード:", self.route_code_combo)
        
        # ルートコード一覧を更新
        self.update_route_codes()
        # デフォルトは空白（update_route_codes()の後に設定）
        self.route_code_combo.setCurrentText("")
        
        return widget

    def create_store_visits_widget(self) -> QWidget:
        """店舗訪問詳細テーブルウィジェットの作成"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # テーブル
        self.store_visits_table = SafeInternalMoveTable()
        self.store_visits_table.setAlternatingRowColors(True)
        self.store_visits_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.store_visits_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        # テキストの省略（...）を無効化
        self.store_visits_table.setTextElideMode(Qt.ElideNone)
        # テキストを折り返して全文表示
        self.store_visits_table.setWordWrap(True)
        
        # ドラッグ＆ドロップを有効化（行間に挿入する設定）
        self.store_visits_table.setDragEnabled(True)
        self.store_visits_table.setAcceptDrops(True)
        self.store_visits_table.setDropIndicatorShown(True)
        self.store_visits_table.setDragDropMode(QTableWidget.InternalMove)
        self.store_visits_table.setDragDropOverwriteMode(False)
        self.store_visits_table.setDefaultDropAction(Qt.MoveAction)
        
        headers = [
            "出力", "訪問順序", "店舗コード", "店舗名", "店舗IN時間", "店舗OUT時間",
            "店舗滞在時間", "移動時間（分）", "想定粗利", "仕入れ点数",
            "店舗評価", "備考"
        ]
        self.store_visits_table.setColumnCount(len(headers))
        self.store_visits_table.setHorizontalHeaderLabels(headers)
        
        header = self.store_visits_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # デフォルトの行高を調整（星評価が綺麗に収まるように）
        self.store_visits_table.verticalHeader().setDefaultSectionSize(24)
        
        # SafeInternalMoveTable の独自シグナルで並び替え後処理を行う
        self.store_visits_table.rows_reordered.connect(self.on_rows_reordered_safe)
        
        # データ変更を監視してUndoスタックに保存
        self.store_visits_table.itemChanged.connect(self.on_table_item_changed)
        
        # ショートカットキーの設定
        self.setup_shortcuts()
        
        layout.addWidget(self.store_visits_table)
        
        # 行追加・削除・全クリア・Undo/Redoボタン
        button_layout = QHBoxLayout()
        add_row_btn = QPushButton("行追加")
        add_row_btn.clicked.connect(lambda: getattr(self, 'add_store_visit_row', lambda: None)())
        button_layout.addWidget(add_row_btn)
        
        delete_row_btn = QPushButton("行削除")
        delete_row_btn.clicked.connect(lambda: getattr(self, 'delete_store_visit_row', lambda: None)())
        button_layout.addWidget(delete_row_btn)
        
        clear_all_btn = QPushButton("全行クリア")
        clear_all_btn.clicked.connect(lambda: getattr(self, 'clear_all_rows', lambda: None)())
        clear_all_btn.setStyleSheet("background-color: #dc3545; color: white;")
        button_layout.addWidget(clear_all_btn)
        
        button_layout.addStretch()
        
        # Undo/Redoボタン
        undo_btn = QPushButton("元に戻す (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo_action)
        undo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(undo_btn)
        
        redo_btn = QPushButton("やり直す (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_action)
        redo_btn.setStyleSheet("background-color: #6c757d; color: white;")
        button_layout.addWidget(redo_btn)
        
        layout.addLayout(button_layout)
        
        return widget

    def setup_calculation_results(self, parent_layout):
        """計算結果表示の設定（非表示）"""
        result_group = QGroupBox("計算結果")
        result_layout = QVBoxLayout(result_group)
        
        self.calculation_label = QLabel("計算結果: データ未入力")
        result_layout.addWidget(self.calculation_label)
        
        # 計算結果エリアを非表示にする
        result_group.setVisible(False)
        
        parent_layout.addWidget(result_group)

