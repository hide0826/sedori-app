#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入管理ウィジェット（オーケストレーター）。"""
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
    _PRICETAR_BROWSER_TITLE_KEYWORDS,
    _WORKFLOW_PIPELINE_SEGMENTS,
    _WORKFLOW_PIPELINE_SEP,
    _ACTION_TO_PIPELINE_STEP,
    _format_status_prefix_html,
    _format_workflow_pipeline_html,
    _normalize_condition_note_newlines,
    _to_stored_newlines,
    _is_repricing_enabled_value,
    SALES_CHANNEL_OPTIONS,
    SHIPPING_METHOD_OPTIONS,
)

from .csv_import_mixin import InventoryCsvImportMixin
from .table_mixin import InventoryTableMixin
from .route_match_mixin import InventoryRouteMatchMixin
from .persistence_mixin import InventoryPersistenceMixin
from .listing_mixin import InventoryListingMixin
from .workflow_mixin import InventoryWorkflowMixin
from .row_edit_dialog import InventoryRowEditDialog  # noqa: F401
from .spot_purchase_dialog import SpotPurchaseDialog
from .single_purchase_dialog import SinglePurchaseInputDialog
from .snapshot_dialog import CombinedSnapshotDialog  # noqa: F401


class InventoryWidget(
    InventoryCsvImportMixin,
    InventoryTableMixin,
    InventoryRouteMatchMixin,
    InventoryPersistenceMixin,
    InventoryListingMixin,
    InventoryWorkflowMixin,
    QWidget,
):
    """仕入管理ウィジェット"""
    data_loaded = Signal(int)  # データ読み込み完了

    sku_generated = Signal(int)  # SKU生成完了

    spot_saved = Signal()  # スポット仕入をルートサマリーに保存した

    def __init__(self, api_client, dev_mode: bool = False):
        super().__init__()
        self.api_client = api_client
        self.dev_mode = bool(dev_mode)
        self.inventory_data = None
        self.filtered_data = None
        self.excluded_highlight_on = False
        # 仕入一覧の見込み利益・損益分岐点の再計算中は itemChanged を無視（ループ防止）
        self._profit_recalc_block = False
        # ワークフロー状態（工程6まで完了して一時停止中かどうか）
        self.workflow_paused_after_step6 = False
        self._last_saved_listing_csv_path: Optional[str] = None
        
        # ルートサマリーウィジェットへの参照（後で設定される）
        self.route_summary_widget = None
        self.antique_widget = None  # 古物台帳ウィジェットへの参照
        self.product_widget = None  # 商品DBウィジェットへの参照
        
        # 3-6-9仕入管理タブも実仕入で使うため、統合保存・DB保存は本番と同じDBを使用する
        # （dev_mode は 3-6-9 列の表示やPRO統計などUI差のみ。保存先は本番と同一）
        self.store_db = StoreDatabase()
        self.inventory_db = InventoryDatabase()
        self.route_snapshot_db = InventoryRouteSnapshotDatabase()
        self.product_db = ProductDatabase()
        self.product_purchase_db = ProductPurchaseDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.warranty_db = WarrantyDatabase()
        from database.condition_template_db import ConditionTemplateDatabase
        from database.route_db import RouteDatabase
        self.condition_template_db = ConditionTemplateDatabase()
        self.route_db = RouteDatabase()
        
        # UIの初期化
        self.route_template_btn = None
        self.matching_btn = None
        self.setup_ui()

    def _close_db_connection(self, db: Any) -> None:
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
        for attr in (
            "store_db",
            "inventory_db",
            "route_snapshot_db",
            "product_db",
            "product_purchase_db",
            "route_visit_db",
            "warranty_db",
            "condition_template_db",
            "route_db",
        ):
            self._close_db_connection(getattr(self, attr, None))
        self.store_db = StoreDatabase()
        self.inventory_db = InventoryDatabase()
        self.route_snapshot_db = InventoryRouteSnapshotDatabase()
        self.product_db = ProductDatabase()
        self.product_purchase_db = ProductPurchaseDatabase()
        self.route_visit_db = RouteVisitDatabase()
        self.warranty_db = WarrantyDatabase()
        from database.condition_template_db import ConditionTemplateDatabase
        from database.route_db import RouteDatabase
        self.condition_template_db = ConditionTemplateDatabase()
        self.route_db = RouteDatabase()
        self.inventory_data = None
        self.filtered_data = None
        if hasattr(self, "data_table"):
            self.update_table()
        if hasattr(self, "generate_sku_btn"):
            self.generate_sku_btn.setEnabled(False)

    def set_route_summary_widget(self, widget):
        self.route_summary_widget = widget
        # ルート登録側に本番/開発どちらの仕入管理ウィジェットかを伝える
        if widget is not None:
            if getattr(self, "dev_mode", False):
                widget.inventory_widget_dev = self
            else:
                widget.inventory_widget_main = self
            # 従来互換用ポインタも更新（本番優先 / なければ開発）
            widget.inventory_widget = widget.inventory_widget_main or widget.inventory_widget_dev
        if self.route_template_btn:
            self.route_template_btn.setEnabled(widget is not None)
        if self.matching_btn:
            self.matching_btn.setEnabled(widget is not None)

    def set_antique_widget(self, widget):
        """古物台帳ウィジェットへの参照を設定"""
        self.antique_widget = widget

    def set_product_widget(self, widget):
        """商品DBウィジェットへの参照を設定"""
        self.product_widget = widget

    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：ファイル操作エリア
        self.setup_file_operations()
        
        # 表示モード切り替え
        self.setup_view_mode_selector()
        
        # 検索・フィルタ・出品設定
        self.setup_search_listing_panel()
        
        # データテーブル（折りたたみ対応）
        self.setup_data_table()
        
        # ルートテンプレート読み込みエリア
        self.setup_route_template_panel()
        
        # スプリッターでエリアの高さを調整可能にする
        self.setup_splitter()
        
        # SKUテンプレ設定パネル（既存機能）
        self.setup_settings_panel()
        
        # 初期表示モード適用
        self.on_view_mode_changed(self.view_mode_combo.currentIndex())

    def setup_file_operations(self):
        """ファイル操作エリアの設定（改良版）"""
        file_group = QGroupBox("ファイル操作・アクション")
        file_outer = QVBoxLayout(file_group)
        file_outer.setSpacing(4)
        file_outer.setContentsMargins(5, 5, 5, 5)
        file_layout = QHBoxLayout()
        green_button_style = """
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """
        
        # ── ワークフロー行（①〜⑧） ──
        workflow_layout = QHBoxLayout()
        workflow_layout.setSpacing(5)

        self.import_btn = QPushButton("CSV取込")
        self.import_btn.clicked.connect(lambda: self._run_action_with_status("CSV取込", self.import_csv))
        self.import_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.import_btn)

        self.route_template_btn = QPushButton("ルートテンプレ読込")
        self.route_template_btn.clicked.connect(
            lambda: self._run_action_with_status("ルートテンプレ読込", self.apply_route_template)
        )
        self.route_template_btn.setEnabled(self.route_summary_widget is not None)
        self.route_template_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.route_template_btn)

        self.matching_btn = QPushButton("照合処理実行")
        self.matching_btn.clicked.connect(
            lambda: self._run_action_with_status("照合処理実行", self.run_matching)
        )
        self.matching_btn.setEnabled(self.route_summary_widget is not None)
        self.matching_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.matching_btn)

        self.generate_sku_btn = QPushButton("SKU生成")
        self.generate_sku_btn.clicked.connect(
            lambda: self._run_action_with_status("SKU生成", self.generate_sku)
        )
        self.generate_sku_btn.setEnabled(False)
        self.generate_sku_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.generate_sku_btn)

        self.db_save_btn = QPushButton("DB保存")
        self.db_save_btn.clicked.connect(
            lambda: self._run_action_with_status("DB保存", self._confirm_condition_edit_then_save_to_databases)
        )
        self.db_save_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.db_save_btn)

        self.antique_register_btn = QPushButton("古物台帳生成")
        self.antique_register_btn.clicked.connect(
            lambda: self._run_action_with_status("古物台帳生成", self.generate_antique_register)
        )
        self.antique_register_btn.setEnabled(False)
        self.antique_register_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.antique_register_btn)

        self.export_listing_btn = QPushButton("出品CSV生成")
        self.export_listing_btn.clicked.connect(
            lambda: self._run_action_with_status("出品CSV生成", self.export_listing_csv)
        )
        self.export_listing_btn.setEnabled(False)
        self.export_listing_btn.setStyleSheet(green_button_style)
        workflow_layout.addWidget(self.export_listing_btn)

        workflow_layout.addStretch()

        self.default_base_folder_btn = QPushButton("デフォルト設定")
        self.default_base_folder_btn.setToolTip("仕入管理タブで使うデフォルトフォルダを設定します。")
        self.default_base_folder_btn.clicked.connect(self.browse_default_base_folder)
        workflow_layout.addWidget(self.default_base_folder_btn)

        self.toggle_settings_btn = QPushButton("SKU設定")
        self.toggle_settings_btn.clicked.connect(self.toggle_settings_panel)
        workflow_layout.addWidget(self.toggle_settings_btn)

        self.data_count_label = QLabel("データ件数: 0")
        workflow_layout.addWidget(self.data_count_label)
        file_outer.addLayout(workflow_layout)

        self._workflow_status_text = "ワークフロー: 未実行"
        self._workflow_emphasize = False
        self._workflow_active_step: Optional[int] = None
        self.workflow_status_label = QLabel()
        self.workflow_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_status_label.setWordWrap(True)
        self.workflow_status_label.setStyleSheet("padding: 2px 0px;")
        self._sync_workflow_status_label()
        file_outer.addWidget(self.workflow_status_label)

        # ── サブボタン行（ワークフロー外） ──
        aux_layout = QHBoxLayout()
        aux_layout.setSpacing(5)

        self.export_btn = QPushButton("CSV出力")
        self.export_btn.clicked.connect(lambda: self._run_action_with_status("CSV出力", self.export_csv))
        self.export_btn.setEnabled(False)
        self.export_btn.setVisible(False)
        aux_layout.addWidget(self.export_btn)

        self.clear_btn = QPushButton("オールクリア")
        self.clear_btn.clicked.connect(lambda: self._run_action_with_status("オールクリア", self.clear_data))
        self.clear_btn.setEnabled(False)
        aux_layout.addWidget(self.clear_btn)

        self.combined_save_btn = QPushButton("統合保存")
        self.combined_save_btn.clicked.connect(
            lambda: self._run_action_with_status("統合保存", self.save_combined_snapshot)
        )
        aux_layout.addWidget(self.combined_save_btn)

        self.combined_load_btn = QPushButton("統合読込")
        self.combined_load_btn.clicked.connect(
            lambda: self._run_action_with_status("統合読込", self.open_combined_snapshot_history)
        )
        aux_layout.addWidget(self.combined_load_btn)

        self.clear_sku_btn = QPushButton("SKUクリア")
        self.clear_sku_btn.setToolTip("仕入データは残したまま、SKU列だけをすべて『未実装』に戻します。")
        self.clear_sku_btn.clicked.connect(lambda: self._run_action_with_status("SKUクリア", self.clear_sku))
        self.clear_sku_btn.setEnabled(False)
        self.clear_sku_btn.setStyleSheet(green_button_style)
        aux_layout.addWidget(self.clear_sku_btn)

        self.single_purchase_btn = QPushButton("単品仕入")
        self.single_purchase_btn.setToolTip("単品仕入の入力ウィンドウを開いて、1件ずつ仕入データへ追加します")
        self.single_purchase_btn.clicked.connect(
            lambda: self._run_action_with_status("単品仕入", self.open_single_purchase_dialog)
        )
        self.single_purchase_btn.setStyleSheet(green_button_style)
        aux_layout.addWidget(self.single_purchase_btn)

        self.spot_purchase_btn = QPushButton("スポット")
        self.spot_purchase_btn.setToolTip(
            "スキマ時間の1店舗スポット仕入をルート情報として登録し、ルートサマリー一覧に残します"
        )
        self.spot_purchase_btn.clicked.connect(
            lambda: self._run_action_with_status("スポット", self.open_spot_purchase_dialog)
        )
        self.spot_purchase_btn.setStyleSheet(green_button_style)
        aux_layout.addWidget(self.spot_purchase_btn)

        aux_layout.addStretch()
        file_outer.addLayout(aux_layout)

        self.listing_drop_panel = QFrame()
        self.listing_drop_panel.setObjectName("listingDropPanel")
        self.listing_drop_panel.setStyleSheet(
            """
            QFrame#listingDropPanel {
                background-color: #1e2a36;
                border: 1px solid #4a6fa5;
                border-radius: 8px;
                margin-top: 4px;
            }
            """
        )
        listing_drop_outer = QVBoxLayout(self.listing_drop_panel)
        listing_drop_outer.setContentsMargins(12, 10, 12, 10)
        listing_drop_outer.setSpacing(8)

        listing_top_row = QHBoxLayout()
        listing_top_row.setSpacing(12)

        self.listing_csv_drag_icon = DraggableFileIconWidget()
        self.listing_csv_drag_icon.set_browser_title_keywords(_PRICETAR_BROWSER_TITLE_KEYWORDS)
        self.listing_csv_drag_icon.set_tooltip_prefix(
            "①「ブラウザで開く」→ ②このアイコンをドラッグしてCSVのドロップ欄へ"
        )
        listing_top_row.addWidget(self.listing_csv_drag_icon)

        listing_text_col = QVBoxLayout()
        listing_text_col.setSpacing(4)
        listing_title = QLabel("プライスター出品用CSV")
        listing_title.setStyleSheet("font-size: 11pt; font-weight: bold; color: #b8d4f0;")
        listing_text_col.addWidget(listing_title)

        self.listing_drop_hint = QLabel(
            "「出品CSV生成」後、「ブラウザで開く」→ 左のCSVアイコンをドラッグしてください"
        )
        self.listing_drop_hint.setWordWrap(True)
        self.listing_drop_hint.setStyleSheet("color: #9eb8d0;")
        listing_text_col.addWidget(self.listing_drop_hint)

        self.listing_drop_filename = QLabel("（出品CSV生成後に表示）")
        self.listing_drop_filename.setWordWrap(True)
        self.listing_drop_filename.setStyleSheet("color: #e8e8e8; font-family: monospace;")
        listing_text_col.addWidget(self.listing_drop_filename)

        listing_btn_row = QHBoxLayout()
        self.listing_open_browser_btn = QPushButton("ブラウザで開く")
        self.listing_open_browser_btn.setToolTip(
            "プライスター CSV入庫画面を既定ブラウザで開きます"
        )
        self.listing_open_browser_btn.clicked.connect(
            lambda: self._open_pricetar_in_browser()
        )
        self.listing_open_browser_btn.setEnabled(False)
        listing_btn_row.addWidget(self.listing_open_browser_btn)

        self.listing_open_folder_btn = QPushButton("保存フォルダを開く")
        self.listing_open_folder_btn.setToolTip("保存した出品CSVがあるフォルダをエクスプローラーで開きます")
        self.listing_open_folder_btn.clicked.connect(self._open_last_listing_csv_folder)
        self.listing_open_folder_btn.setEnabled(False)
        listing_btn_row.addWidget(self.listing_open_folder_btn)

        listing_btn_row.addStretch()
        listing_text_col.addLayout(listing_btn_row)

        listing_top_row.addLayout(listing_text_col, 1)
        listing_drop_outer.addLayout(listing_top_row)

        self.listing_drop_panel.setVisible(False)
        file_outer.addWidget(self.listing_drop_panel)

        file_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        # グループボックスをメインレイアウトに追加
        self.layout().addWidget(file_group)

        # デフォルトフォルダ設定をロード
        self._load_default_base_folder()

    def setup_view_mode_selector(self):
        selector_layout = QHBoxLayout()
        mode_label = QLabel("表示モード:")
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["デフォルト", "仕入データビュー", "ルートテンプレートビュー"])
        self.view_mode_combo.currentIndexChanged.connect(self.on_view_mode_changed)
        selector_layout.addWidget(mode_label)
        selector_layout.addWidget(self.view_mode_combo)
        selector_layout.addStretch()
        self.layout().addLayout(selector_layout)
        self.view_mode_combo.setCurrentIndex(0)

    def on_view_mode_changed(self, index: int):
        mode = self.view_mode_combo.currentText()
        search_group = getattr(self, "search_listing_group", None)
        data_group = getattr(self, "data_group", None)
        template_group = getattr(self, "route_template_group", None)
        if mode == "デフォルト":
            if search_group:
                search_group.setVisible(True)
            if data_group:
                data_group.setVisible(True)
            if template_group:
                template_group.setVisible(True)
        elif mode == "仕入データビュー":
            if search_group:
                search_group.setVisible(True)
            if data_group:
                data_group.setVisible(True)
            if template_group:
                template_group.setVisible(False)
        elif mode == "ルートテンプレートビュー":
            if search_group:
                search_group.setVisible(False)
            if data_group:
                data_group.setVisible(False)
            if template_group:
                template_group.setVisible(True)
        
        # 表示モード切り替え後にテーブルのサイズを再調整
        # レイアウトの再計算を促す
        if hasattr(self, 'data_table'):
            # テーブルのサイズポリシーを確認し、必要に応じて再設定
            self.data_table.updateGeometry()
            # 親ウィジェットのレイアウトを更新
            if self.data_table.parent():
                self.data_table.parent().updateGeometry()
            # データがある場合はテーブルを再更新して全行が表示されるようにする
            if self.filtered_data is not None and len(self.filtered_data) > 0:
                # テーブルの行数を確認し、必要に応じて再設定
                current_rows = self.data_table.rowCount()
                expected_rows = len(self.filtered_data)
                if current_rows != expected_rows:
                    # 行数が一致しない場合は再更新
                    self.update_table()

    def _get_qsettings(self) -> QSettings:
        # 開発モード時は別アプリ名で保存し、本番の設定と混在しないようにする
        if getattr(self, "dev_mode", False):
            return QSettings("HIRIO", "SedoriDesktopApp_InventoryDev")
        return QSettings("HIRIO", "SedoriDesktopApp")

    def setup_splitter(self):
        """スプリッターでエリアの高さを調整可能にする"""
        # スプリッターを作成（縦方向）
        self.area_splitter = QSplitter(Qt.Vertical)
        
        # エリアをスプリッターに追加
        self.area_splitter.addWidget(self.data_group)
        self.area_splitter.addWidget(self.route_template_group)
        
        # 初期の高さ比率を設定（データエリア: ルートエリア = 3:1）
        self.area_splitter.setStretchFactor(0, 3)  # データエリア
        self.area_splitter.setStretchFactor(1, 1)  # ルートエリア
        
        # スプリッターの状態変更を監視して保存
        self.area_splitter.splitterMoved.connect(self.save_splitter_state)
        
        # レイアウトに追加
        self.layout().addWidget(self.area_splitter, 1)  # stretch factor = 1
        
        # ウィンドウが表示された後にスプリッターの状態を復元
        # showEventまたはタイマーで遅延復元
        from PySide6.QtCore import QTimer
        restore_timer = QTimer()
        restore_timer.setSingleShot(True)
        restore_timer.timeout.connect(self.restore_splitter_state)
        restore_timer.start(100)  # 100ms後に復元

    def save_splitter_state(self):
        """スプリッターの状態を保存（デバウンス処理付き）"""
        # 頻繁に呼ばれるので、少し遅延させてから保存
        if not hasattr(self, '_splitter_save_timer'):
            from PySide6.QtCore import QTimer
            self._splitter_save_timer = QTimer()
            self._splitter_save_timer.setSingleShot(True)
            def _batched_save():
                try:
                    s = self._get_qsettings()
                    # スプリッターの各エリアのサイズを保存
                    sizes = self.area_splitter.sizes()
                    if len(sizes) >= 2:
                        s.setValue("inventory/splitter_data_height", sizes[0])
                        s.setValue("inventory/splitter_route_height", sizes[1])
                except Exception as e:
                    print(f"スプリッター状態保存エラー: {e}")
            self._splitter_save_timer.timeout.connect(_batched_save)
        
        # タイマーをリセット（500ms後に保存）
        self._splitter_save_timer.stop()
        self._splitter_save_timer.start(500)

    def restore_splitter_state(self):
        """スプリッターの状態を復元"""
        try:
            s = self._get_qsettings()
            data_height = s.value("inventory/splitter_data_height", None, type=int)
            route_height = s.value("inventory/splitter_route_height", None, type=int)
            
            if data_height is not None and route_height is not None and data_height > 0 and route_height > 0:
                # 保存されたサイズを復元
                self.area_splitter.setSizes([data_height, route_height])
            else:
                # デフォルトの比率を設定（データエリア: ルートエリア = 3:1）
                # 実際のサイズはウィンドウサイズに応じて自動調整される
                pass
        except Exception as e:
            print(f"スプリッター状態復元エラー: {e}")

    def save_settings(self):
        """ウィジェットの設定を保存（スプリッターの状態も含む）"""
        # スプリッターの状態を即座に保存（タイマーを待たずに）
        if hasattr(self, 'area_splitter'):
            try:
                s = self._get_qsettings()
                sizes = self.area_splitter.sizes()
                if len(sizes) >= 2:
                    s.setValue("inventory/splitter_data_height", sizes[0])
                    s.setValue("inventory/splitter_route_height", sizes[1])
            except Exception as e:
                print(f"スプリッター状態保存エラー: {e}")

    def open_spot_purchase_dialog(self):
        """スポット仕入用のルート情報入力ダイアログを開き、SPOTルートを自動作成する"""
        # 仕入データから日付の初期値を推定（うまく取れなければ今日）
        default_date = QDate.currentDate()
        try:
            if self.inventory_data is not None and len(self.inventory_data) > 0 and "仕入れ日" in self.inventory_data.columns:
                raw = self.inventory_data.iloc[0]["仕入れ日"]
                dt = pd.to_datetime(raw, errors="coerce")
                if dt is not pd.NaT:
                    default_date = QDate(dt.year, dt.month, dt.day)
        except Exception:
            pass
        dlg = SpotPurchaseDialog(self.store_db, self.inventory_data, default_date, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            visit = dlg.get_spot_visit()
            store_code = visit.get("store_code", "")
            store_name = visit.get("store_name", "")
            in_time = visit.get("store_in_time", "")
            out_time = visit.get("store_out_time", "")
            stay_min = visit.get("stay_duration", 0)
            if not self.route_summary_widget:
                QMessageBox.warning(self, "ルート機能", "ルート登録タブが初期化されていません。")
                return
            # ルート日付はダイアログでユーザーが選んだ日付を使用
            route_date_q = dlg.get_route_date_qdate()
            self.route_summary_widget.route_date_edit.setDateTime(QDateTime(route_date_q, QTime.currentTime()))
            route_code = f"SPOT-{store_code}" if store_code else "SPOT"
            # ルートコードコンボは「名前」ベースだが、コードが未登録ならそのまま使う
            self.route_summary_widget.route_code_combo.setCurrentText(route_code)
            # 店舗訪問テーブルを1行にリセットしてスポット行を追加
            table = self.route_summary_widget.store_visits_table
            table.setRowCount(0)
            table.insertRow(0)
            memo_text = ""
            if store_code:
                store_info = self.store_db.get_store_by_code(store_code)
                if store_info:
                    custom_fields = store_info.get("custom_fields", {})
                    memo_text = custom_fields.get("notes", "")
            try:
                gross = str(int(dlg.gross_profit_edit.text() or 0))
            except ValueError:
                gross = "0"
            try:
                qty = str(int(dlg.item_count_edit.text() or 0))
            except ValueError:
                qty = "0"
            self.route_summary_widget._fill_visit_table_row(
                0,
                store_code=store_code,
                store_name=store_name,
                in_time=in_time,
                out_time=out_time,
                stay=str(stay_min),
                travel="",
                profit=gross,
                qty=qty,
                rating=float(dlg.rating_spin.value()),
                notes=memo_text,
                include_checked=True,
                visit_order="1",
                order_editable=False,
            )
            # ルートを保存して route_summaries / store_visit_details に反映
            self.route_summary_widget.save_data()
            # 仕入管理側のルート情報表示を最新状態に更新
            self.refresh_route_template_view()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"スポット仕入ルート追加中にエラーが発生しました:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def open_single_purchase_dialog(self):
        """単品仕入ダイアログを開き、入力データを仕入一覧へ1行追加する"""
        dlg = SinglePurchaseInputDialog(
            self.condition_template_db,
            self._get_condition_key,
            inventory_widget=self,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            row_data = dlg.get_row_data()
            if self.inventory_data is None or len(self.inventory_data) == 0:
                self.inventory_data = pd.DataFrame(columns=self.column_headers)

            row_df = pd.DataFrame([row_data])
            for col in self.column_headers:
                if col not in row_df.columns:
                    row_df[col] = ""
            row_df = row_df[self.column_headers]

            self.inventory_data = pd.concat([self.inventory_data, row_df], ignore_index=True)
            self.filtered_data = self.inventory_data.copy()

            self.update_table()
            self.update_stats()
            self.update_data_count()

            self.clear_btn.setEnabled(True)
            self.generate_sku_btn.setEnabled(True)
            self.export_listing_btn.setEnabled(True)
            self.antique_register_btn.setEnabled(True)

            self.data_loaded.emit(len(self.inventory_data))
            QMessageBox.information(self, "単品仕入", "単品仕入データを1件追加しました。")
        except Exception as e:
            QMessageBox.critical(self, "単品仕入エラー", f"単品仕入の追加に失敗しました:\n{str(e)}")

