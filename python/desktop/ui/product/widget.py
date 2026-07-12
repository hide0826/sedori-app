#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品データベース閲覧・編集ウィジェット（オーケストレーター）。"""
from __future__ import annotations

import sys
import os
import re
import unicodedata
import calendar
from datetime import datetime, date
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple, Iterable
import copy
import json
import logging

from PySide6.QtCore import Qt, QMimeData, QUrl, QSettings, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel, QTabWidget, QHeaderView, QFileDialog, QMenu, QApplication,
    QAbstractItemView, QComboBox, QProgressDialog, QCheckBox, QToolButton, QScrollArea, QFrame,
    QSizePolicy, QStyledItemDelegate,
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor, QColor

from desktop.utils.ui_utils import (
    save_table_header_state, restore_table_header_state,
    save_table_column_widths, restore_table_column_widths
)

logger = logging.getLogger(__name__)

try:
    from utils._desktop_import_compat import (
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        SCROLL_LOAD_THRESHOLD_PX,
        apply_monthly_auto_ladder_to_record,
        augment_purchase_cost_records,
        backfill_condition_label_in_record,
        backfill_purchase_date_from_sku,
        calc_elapsed_days_for_purchase_record as _calc_elapsed_days_for_purchase_record,
        compute_break_even_for_record,
        fee_storage_value,
        fill_purchase_record_tp_from_369,
        get_augment_batch_size,
        get_page_size,
        is_amazon_sales_channel,
        is_eligible_for_monthly_auto,
        is_fee_amount_column,
        is_incremental_render_enabled,
        load_369_repricer_config,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
        purchase_record_purchase_timestamp,
        resolve_local_image_path,
        resolve_record_product_images,
        should_recompute_break_even,
        sort_purchase_records_for_display,
        summarize_repricing_row,
    )
    from utils._desktop_ui_compat import PurchaseRowEditDialog
except ImportError:
    from desktop.utils._desktop_import_compat import (  # type: ignore
        COL_PLATFORM_FEE,
        COL_SHIPPING,
        COL_TOTAL_COST,
        SCROLL_LOAD_THRESHOLD_PX,
        apply_monthly_auto_ladder_to_record,
        augment_purchase_cost_records,
        backfill_condition_label_in_record,
        backfill_purchase_date_from_sku,
        calc_elapsed_days_for_purchase_record as _calc_elapsed_days_for_purchase_record,
        compute_break_even_for_record,
        fee_storage_value,
        fill_purchase_record_tp_from_369,
        get_augment_batch_size,
        get_page_size,
        is_amazon_sales_channel,
        is_eligible_for_monthly_auto,
        is_fee_amount_column,
        is_incremental_render_enabled,
        load_369_repricer_config,
        merge_purchase_history_db_into_display_records,
        normalize_status_code,
        purchase_record_purchase_timestamp,
        resolve_local_image_path,
        resolve_record_product_images,
        should_recompute_break_even,
        sort_purchase_records_for_display,
        summarize_repricing_row,
    )
    from desktop.utils._desktop_ui_compat import PurchaseRowEditDialog  # type: ignore

from .support import (
    PRODUCT_NAME_DISPLAY_LIMIT,
    SortableDateItem,
    PurchaseFullTextItemDelegate,
    DraggableTableWidget,
    ProductEditDialog,
    _PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV,
    _PURCHASE_RIGHT_ALIGN_NUMERIC_HEADERS,
    _PURCHASE_STATUS_FILTER_OPTIONS,
    _PURCHASE_CHANNEL_FILTER_OPTIONS,
    _PURCHASE_FILE_PATH_COLUMNS,
    _PURCHASE_URL_COLUMNS,
    _PURCHASE_FULLTEXT_MIN_COLUMN_WIDTH,
    _purchase_numeric_cell_text,
    _make_purchase_numeric_table_item,
    _purchase_record_sales_channel,
    _purchase_record_shipping_method,
    purchase_record_matches_amazon_mfn_filter,
    purchase_record_matches_non_amazon_channel_filter,
    _purchase_table_cell_full_text,
)

from database.product_db import ProductDatabase
from database.warranty_db import WarrantyDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from database.purchase_db import PurchaseDatabase
from database.store_db import StoreDatabase
from desktop.database.sales_db import SalesDatabase

from .purchase_table_mixin import PurchaseTableMixin
from .purchase_batch_mixin import PurchaseBatchMixin
from .purchase_edit_mixin import PurchaseEditMixin


class ProductWidget(
    PurchaseTableMixin,
    PurchaseBatchMixin,
    PurchaseEditMixin,
    QWidget,
):
    """商品・仕入・販売タブの本体。"""
    def __init__(self, parent=None, inventory_widget=None, api_client=None):
        super().__init__(parent)
        self.api_client = api_client
        self.settings = QSettings("HIRIO", "DesktopApp")
        # DBハンドルの初期化（軽量処理）
        self.db = ProductDatabase()
        self.warranty_db = WarrantyDatabase()
        self.purchase_db = ProductPurchaseDatabase()  # スナップショット用
        self.purchase_history_db = PurchaseDatabase()
        self.store_db = StoreDatabase()
        self.sales_db = SalesDatabase()
        
        from database.receipt_db import ReceiptDatabase
        self.receipt_db = ReceiptDatabase()
        self.inventory_widget = inventory_widget
        self.inventory_columns = self._resolve_inventory_columns()
        self.purchase_columns: List[str] = list(self.inventory_columns)
        self.purchase_records: List[Dict[str, Any]] = []
        self.sales_records: List[Dict[str, Any]] = []
        self._purchase_edit_dialogs: List[QDialog] = []
        # 仕入DB行の一意IDカウンタ（ソートしても行を特定できるようにする）
        self._purchase_row_id_counter: int = 1
        # 仕入DBテーブルがマスター全件で構築済みなら、フィルタは行の表示/非表示のみ（全再描画を避ける）
        self._purchase_table_full_master_built: bool = False
        # レシート/保証書 DBルックアップキャッシュ（ファイル名→解決パス）
        self._receipt_file_path_cache: Dict[str, Optional[str]] = {}
        self._receipt_info_by_key_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._warranty_sku_path_cache: Dict[str, Optional[str]] = {}
        # 重いデータ読み込みが完了しているかどうか
        self._initial_data_loaded: bool = False
        self._initial_load_in_progress: bool = False
        self._purchase_lookup_loaded: bool = False
        self._purchase_loaded: bool = False
        self._sales_loaded: bool = False
        # 仕入DBテーブル段階読み込み（設定で無効化可能＝従来の全件描画に戻せる）
        self._purchase_incremental_active: bool = False
        self._purchase_incremental_display_records: List[Dict[str, Any]] = []
        self._purchase_incremental_rendered: int = 0
        self._purchase_incremental_loading_more: bool = False
        self._purchase_augmented_through: int = 0
        self._purchase_scroll_load_connected: bool = False
        self._products_loaded: bool = False

        self.setup_ui()
        # テーブルの列幅を復元（データ件数に依存しない軽量処理）
        restore_table_header_state(self.table, "ProductWidget/ProductTableState")
        # sales_tableもヘッダー状態のみ復元（列幅など）
        restore_table_header_state(self.sales_table, "ProductWidget/SalesTableState")

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
            "db",
            "warranty_db",
            "purchase_db",
            "purchase_history_db",
            "store_db",
            "sales_db",
            "receipt_db",
        ):
            self._close_db_connection(getattr(self, attr, None))
        self.db = ProductDatabase()
        self.warranty_db = WarrantyDatabase()
        self.purchase_db = ProductPurchaseDatabase()
        self.purchase_history_db = PurchaseDatabase()
        self.store_db = StoreDatabase()
        self.sales_db = SalesDatabase()
        from database.receipt_db import ReceiptDatabase
        self.receipt_db = ReceiptDatabase()
        self.purchase_records = []
        self.purchase_all_records = []
        self.purchase_all_records_master = []
        self._purchase_loaded = False
        self._purchase_lookup_loaded = False
        self._initial_data_loaded = False
        if hasattr(self, "populate_purchase_table"):
            self.populate_purchase_table([])
        if hasattr(self, "update_purchase_count_label"):
            self.update_purchase_count_label()

        # テーブルの列幅を復元（データ件数に依存しない軽量処理）
        restore_table_header_state(self.table, "ProductWidget/ProductTableState")
        # sales_tableもヘッダー状態のみ復元（列幅など）
        restore_table_header_state(self.sales_table, "ProductWidget/SalesTableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "ProductWidget/ProductTableState")
        save_table_column_widths(self.purchase_table, "ProductWidget/PurchaseTableColumnWidths")
        save_table_header_state(self.sales_table, "ProductWidget/SalesTableState")

    @contextmanager
    def _initial_db_load_busy_scope(self):
        """データベース管理タブ初回表示時の待機表示（砂時計＋くるくるダイアログ）。"""
        progress = QProgressDialog(
            "商品DB・仕入DB・販売データを読み込んでいます...",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("データベース管理")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.setEnabled(False)
        parent_tabs = self.parent()
        if isinstance(parent_tabs, QTabWidget):
            parent_tabs.setEnabled(False)
        QApplication.processEvents()
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
            self.setEnabled(True)
            if isinstance(parent_tabs, QTabWidget):
                parent_tabs.setEnabled(True)
            QApplication.processEvents()

    def ensure_purchase_records_for_lookup(self) -> bool:
        """
        画像管理タブなどから仕入DBを参照するための軽量読み込み。

        スナップショットをメモリに載せるだけで、テーブル描画や
        SKUごとのDB照会（_augment_purchase_records）は行わない。
        """
        if self._initial_data_loaded:
            return bool(getattr(self, "purchase_all_records", None))
        if self._purchase_lookup_loaded and getattr(self, "purchase_all_records", None):
            return True

        if not getattr(self, "purchase_all_records", None):
            self.restore_latest_purchase_snapshot()

        self._purchase_lookup_loaded = bool(self.purchase_all_records)
        return self._purchase_lookup_loaded

    def ensure_initial_data_loaded(self) -> None:
        """
        初回は仕入DBのみを読み込む（販売DBはタブ表示時に遅延読込）。
        - 起動直後には実行せず、タブが初めて表示されたタイミングなどで呼び出す。
        """
        if self._initial_data_loaded or self._initial_load_in_progress:
            return

        self._initial_load_in_progress = True
        try:
            with self._initial_db_load_busy_scope():
                # 軽量読込済みならスナップショット復元は省略
                if not getattr(self, "purchase_all_records", None):
                    self.restore_latest_purchase_snapshot()
                QApplication.processEvents()
                # 仕入テーブルのみ先に反映
                self.load_purchase_data(self.purchase_records)
                QApplication.processEvents()
                self._purchase_loaded = True

            self._initial_data_loaded = True
            self._purchase_lookup_loaded = True
        finally:
            self._initial_load_in_progress = False

    def showEvent(self, event):
        """
        タブとして初めて表示されたタイミングで重いデータ読み込みを行う。
        """
        super().showEvent(event)
        try:
            self.ensure_initial_data_loaded()
        except Exception as e:
            # 初期読み込みで例外が出てもアプリ全体が落ちないようにしておく
            logging.getLogger(__name__).warning(f"ProductWidget initial load error: {e}")

    def _on_inner_tab_changed(self, index: int) -> None:
        """商品DB内サブタブの遅延読込。"""
        try:
            if index < 0:
                return
            label = self.tab_widget.tabText(index)
            if label == "販売DB" and not self._sales_loaded:
                self.load_sales_data()
                self._sales_loaded = True
        except Exception as e:
            logging.getLogger(__name__).warning(f"ProductWidget tab lazy-load error: {e}")

    def _resolve_inventory_columns(self) -> List[str]:
        """仕入管理タブの列構成を取得（未設定時はデフォルト）"""
        base = []
        if self.inventory_widget is not None:
            headers = getattr(self.inventory_widget, "column_headers", None)
            if headers:
                # コピーして改変から保護
                base = list(headers)
        
        # デフォルトのベース列（inventory_widgetがない場合）
        if not base:
            base = [
                "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
                "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点",
                "想定利益率", "想定ROI", "コメント",
                "発送方法", "販売チャネル",
                COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST,
                "仕入先", "コンディション説明",
            ]

        # TP0〜TP3 は末尾に配置（3-6-9価格改定専用のため通常業務列から分離）
        for col in ["TP0", "TP1", "TP2", "TP3"]:
            while col in base:
                base.remove(col)
        base.extend(["TP0", "TP1", "TP2", "TP3"])

        # コンディション説明の後に挿入するカラム（順序重要）
        insert_after_condition_note = [
            "ステータス",
            "ステータス理由",
            "レシート画像",
            "レシート画像URL",  # レシート画像の後に追加
            "保証書画像",  # 保証書IDから変更
            "保証期間",
            "保証最終日"  # 新規追加
        ]
        
        # その他の追加カラム
        extra_columns = [
            # 画像列
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
            # 画像URL列
            "画像URL1", "画像URL2", "画像URL3", "画像URL4", "画像URL5", "画像URL6",
            # 改定サマリ（価格改定の直前に表示）
            "月別",
            "改定価格",
            # 価格改定ON/OFF（右端）
            "価格改定",
        ]
        
        # コンディション説明の位置を探して、その後にカラムを挿入
        if "コンディション説明" in base:
            condition_note_idx = base.index("コンディション説明")
            # 既存の「保証期間」「レシート画像」「保証書ID」を削除（あれば）
            for old_col in ["保証期間", "レシート画像", "保証書ID"]:
                if old_col in base:
                    base.remove(old_col)
            # コンディション説明の後に挿入
            for i, col in enumerate(insert_after_condition_note):
                if col not in base:
                    base.insert(condition_note_idx + 1 + i, col)
        else:
            # コンディション説明がない場合は末尾に追加
            for col in insert_after_condition_note:
                if col not in base:
                    base.append(col)
        
        # その他のカラムを追加（既存の「保証期間」「レシート画像」「保証書ID」を削除済み）
        for col in extra_columns:
            if col not in base:
                base.append(col)
                
        return base

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QLabel("商品データベース")
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(header)

        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # 商品一覧タブはUIには追加しないが、既存処理のため初期化だけ行う
        self.product_tab = QWidget()
        self.setup_product_tab()
        self.product_tab.hide()

        # 仕入DBタブ
        self.purchase_tab = QWidget()
        self.setup_purchase_tab()
        self.tab_widget.addTab(self.purchase_tab, "仕入DB")

        # 販売DBタブ（仮）
        self.sales_tab = QWidget()
        self.setup_sales_tab()
        self.tab_widget.addTab(self.sales_tab, "販売DB")
        self.tab_widget.currentChanged.connect(self._on_inner_tab_changed)
        self.tab_widget.setCurrentWidget(self.purchase_tab)

    def setup_product_tab(self):
        layout = QVBoxLayout(self.product_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        controls_layout = QHBoxLayout()
        self.reload_button = QPushButton("再読み込み")
        self.reload_button.clicked.connect(self.load_products)
        controls_layout.addWidget(self.reload_button)

        self.add_button = QPushButton("商品追加")
        self.add_button.clicked.connect(self.on_add_product)
        controls_layout.addWidget(self.add_button)

        self.edit_button = QPushButton("編集")
        self.edit_button.clicked.connect(self.on_edit_product)
        controls_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("削除")
        self.delete_button.clicked.connect(self.on_delete_product)
        controls_layout.addWidget(self.delete_button)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.table = QTableWidget()
        self.table._hirio_table_column_settings_key = "table_column_widths/ProductWidget/ProductTable"
        self.table._hirio_table_column_legacy_keys = ["ProductWidget/ProductTableState"]
        self.table.setColumnCount(17)  # 11 + 6 (画像1〜6)
        self.table.setHorizontalHeaderLabels([
            "SKU", "商品名", "JAN", "ASIN", "仕入日", "仕入価格",
            "数量", "店舗コード", "店舗名", "保証期間(日)", "保証満了日",
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        # セルクリックイベントを接続（画像列のクリック処理用）
        self.table.cellClicked.connect(self.on_product_table_cell_clicked)
        layout.addWidget(self.table)

    def setup_purchase_tab(self):
        layout = QVBoxLayout(self.purchase_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 検索エリア
        search_group = QGroupBox("検索")
        search_layout = QGridLayout()
        
        # 統合キーワード検索（日付・SKU・ASIN・JAN・商品名）
        search_layout.addWidget(QLabel("キーワード:"), 0, 0)
        self.purchase_search_query = QLineEdit()
        self.purchase_search_query.setPlaceholderText(
            "日付・SKU・ASIN・JAN・商品名を部分一致で検索"
        )
        self.purchase_search_query.returnPressed.connect(self.filter_purchase_records)
        search_layout.addWidget(self.purchase_search_query, 0, 1, 1, 7)
        
        # ステータスフィルタ（複数チェック・折りたたみ可能）
        status_filter_panel = self._build_purchase_status_collapsible_filter()
        search_layout.addWidget(status_filter_panel, 1, 0, 1, 10)

        repricing_filter_row = QHBoxLayout()
        repricing_filter_row.setContentsMargins(0, 0, 0, 0)
        repricing_filter_row.setSpacing(12)
        self.purchase_filter_ladder_only = QCheckBox("月別ONのみ")
        self.purchase_filter_ladder_only.setToolTip("月別運用（30日刻みルール）がONの行だけ表示します。")
        self.purchase_filter_ladder_only.stateChanged.connect(self._on_purchase_repricing_filter_changed)
        repricing_filter_row.addWidget(self.purchase_filter_ladder_only)
        self.purchase_filter_repricing_incomplete = QCheckBox("改定価格 未完了のみ")
        self.purchase_filter_repricing_incomplete.setToolTip(
            "価格改定ONの行のうち、入力が足りない行だけ表示します。\n"
            "月別運用: 経過済み帯を除いた現在以降の帯で目標到達価格が未入力。\n"
            "4段モード: TP0〜TP3 のいずれかが空欄。"
        )
        self.purchase_filter_repricing_incomplete.stateChanged.connect(
            self._on_purchase_repricing_filter_changed
        )
        repricing_filter_row.addWidget(self.purchase_filter_repricing_incomplete)
        repricing_filter_row.addStretch(1)
        search_layout.addLayout(repricing_filter_row, 2, 0, 1, 10)
        
        # 検索ボタン
        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self.filter_purchase_records)
        search_layout.addWidget(search_btn, 0, 8)
        
        # クリアボタン
        clear_btn = QPushButton("クリア")
        clear_btn.clicked.connect(self.clear_purchase_search)
        search_layout.addWidget(clear_btn, 0, 9)

        search_group.setLayout(search_layout)
        layout.addWidget(search_group)

        # コントロールボタン
        controls_layout = QHBoxLayout()
        
        # 行操作ボタン
        self.delete_purchase_row_button = QPushButton("行削除")
        self.delete_purchase_row_button.clicked.connect(self.on_delete_purchase_row)
        controls_layout.addWidget(self.delete_purchase_row_button)

        self.delete_all_purchase_button = QPushButton("全行削除")
        self.delete_all_purchase_button.clicked.connect(self.on_delete_all_purchase)
        controls_layout.addWidget(self.delete_all_purchase_button)

        controls_layout.addWidget(QLabel("|"))  # 区切り
        
        # 表示切り替えボタン
        self.view_all_button = QPushButton("ALL")
        self.view_all_button.setCheckable(True)
        self.view_all_button.setChecked(True)  # デフォルトで全表示
        self.view_all_button.clicked.connect(lambda: self.toggle_view_mode("all"))
        controls_layout.addWidget(self.view_all_button)
        
        self.view_status_button = QPushButton("ステータス")
        self.view_status_button.setCheckable(True)
        self.view_status_button.clicked.connect(lambda: self.toggle_view_mode("status"))
        controls_layout.addWidget(self.view_status_button)
        
        # TP列だけにフォーカスする表示切り替えボタン
        self.view_tp_button = QPushButton("TP")
        self.view_tp_button.setCheckable(True)
        self.view_tp_button.clicked.connect(lambda: self.toggle_view_mode("tp"))
        controls_layout.addWidget(self.view_tp_button)

        self.autofill_tp369_button = QPushButton("TP自動(369)")
        self.autofill_tp369_button.setToolTip(
            "TP0〜TP3 が空欄の行だけ、SKU の 3P/6N などと「3-6-9価格改定」の TP 利益保持率(%)で自動入力します。\n"
            "価格は「損益分岐点 + 保持率×(販売予定−損益分岐点)」で求め、販売予定価格を超えません。\n"
            "保持率 0%% の帯は損益分岐点。損益分岐が取れないときは列の値または従来のフォールバックを使います。\n"
            "既に値がある列は上書きしません。"
        )
        self.autofill_tp369_button.clicked.connect(self.autofill_purchase_tp_from_369_rules)
        controls_layout.addWidget(self.autofill_tp369_button)

        self.clear_tp_dev_button = QPushButton("TPクリア(開発)")
        self.clear_tp_dev_button.setToolTip(
            "【開発用】仕入DBの全行から TP0〜TP3 を空にします。\n"
            "スナップショットと hiroi.db の該当 SKU にも反映します。取り消しはできません。"
        )
        self.clear_tp_dev_button.clicked.connect(self.clear_all_purchase_tp_for_dev)
        controls_layout.addWidget(self.clear_tp_dev_button)
        
        self.view_image_button = QPushButton("画像")
        self.view_image_button.setCheckable(True)
        self.view_image_button.clicked.connect(lambda: self.toggle_view_mode("image"))
        controls_layout.addWidget(self.view_image_button)
        
        self.view_ledger_button = QPushButton("古物台帳")
        self.view_ledger_button.setCheckable(True)
        self.view_ledger_button.clicked.connect(lambda: self.toggle_view_mode("ledger"))
        controls_layout.addWidget(self.view_ledger_button)

        # 店舗コードバッチ更新ボタン（仕入先→新店舗コードへ一括変換）
        self.update_store_codes_button = QPushButton("店舗コードバッチ")
        self.update_store_codes_button.setToolTip("仕入DBの『仕入先』カラムを店舗マスタの新店舗コードに置き換えます")
        self.update_store_codes_button.clicked.connect(self.batch_update_store_codes_from_master)
        controls_layout.addWidget(self.update_store_codes_button)

        self.autofill_monthly_ladder_button = QPushButton("月別自動")
        self.autofill_monthly_ladder_button.setToolTip(
            "TP0〜TP3 がすべて空で、月別運用がOFFの行に対し、一括で次を設定します。\n"
            "・月別運用 ON\n"
            "・全帯: アクション priceTrace / priceTrace設定 FBA状態合わせ\n"
            "・akaji下限 2% / takane上限 1%\n"
            "・現在以降〜331-360日帯まで等間隔値下げ（最終利益率 0%）\n"
            "既に月別ONまたはTP入力済みの行はスキップします。"
        )
        self.autofill_monthly_ladder_button.clicked.connect(self.autofill_purchase_monthly_ladder_batch)
        controls_layout.addWidget(self.autofill_monthly_ladder_button)

        # 仕入DB保存ボタン（手動変更を含めて確実にスナップショット保存）
        self.save_purchase_button = QPushButton("仕入DB保存")
        self.save_purchase_button.setToolTip("現在の仕入DBの内容（テーブル上の変更を含む）をスナップショットとして保存します")
        self.save_purchase_button.clicked.connect(self.save_purchase_from_table)
        controls_layout.addWidget(self.save_purchase_button)

        self.reload_purchase_button = QPushButton("仕入DB再読込")
        self.reload_purchase_button.setToolTip(
            "最新のスナップショットから仕入DBを読み直します。\n"
            "表示が1件だけ・空行が多いときの復旧用です。"
        )
        self.reload_purchase_button.clicked.connect(self.reload_purchase_from_latest_snapshot)
        controls_layout.addWidget(self.reload_purchase_button)

        self.purchase_count_label = QLabel("保存件数: 0件")
        controls_layout.addWidget(self.purchase_count_label)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # 表示モードを初期化
        self.purchase_view_mode = "all"

        # 仕入DBテーブル
        self.purchase_table = DraggableTableWidget()  # ドラッグ対応テーブルに変更
        self.purchase_table._hirio_table_column_settings_key = (
            "table_column_widths/ProductWidget/PurchaseTableColumnWidths"
        )
        self.purchase_table._hirio_table_column_legacy_keys = [
            "ProductWidget/PurchaseTableColumnWidths",
        ]
        self.purchase_table.setAlternatingRowColors(True)
        self.purchase_table.setSelectionBehavior(QTableWidget.SelectRows)
        # 編集トリガーを設定（選択＋クリック、F2キーで編集可能）
        # ダブルクリックでは編集モードに入らないようにして、
        # 画像URL列のダブルクリックでブラウザを開けるようにする
        # ただし、ItemIsEditableフラグが設定されているセルのみ編集可能
        self.purchase_table.setEditTriggers(
            QTableWidget.SelectedClicked |
            QTableWidget.EditKeyPressed
        )
        
        # ソート機能を有効化
        self.purchase_table.setSortingEnabled(True)
        
        # カスタムコンテキストメニューを有効化
        self.purchase_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.purchase_table.customContextMenuRequested.connect(self._show_purchase_context_menu)
        # セルダブルクリック時の処理を追加
        # （レシート画像や画像URLをダブルクリックしたときに画像/URLを開く）
        self.purchase_table.cellDoubleClicked.connect(self.on_purchase_table_cell_clicked)
        self.purchase_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # SKU・商品名など長いテキストを省略表示（...）にしない（3-6-9仕入管理保存時などでフル表示）
        self.purchase_table.setTextElideMode(Qt.ElideNone)
        
        layout.addWidget(self.purchase_table)

    def setup_sales_tab(self):
        layout = QVBoxLayout(self.sales_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        controls_layout = QHBoxLayout()
        self.import_sales_csv_button = QPushButton("CSV取込")
        self.import_sales_csv_button.clicked.connect(self.import_sales_csv)
        controls_layout.addWidget(self.import_sales_csv_button)

        self.reload_sales_button = QPushButton("再読み込み")
        self.reload_sales_button.clicked.connect(self.load_sales_data)
        controls_layout.addWidget(self.reload_sales_button)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        self.sales_table = QTableWidget()
        self.sales_table._hirio_table_column_settings_key = "table_column_widths/ProductWidget/SalesTable"
        self.sales_table._hirio_table_column_legacy_keys = ["ProductWidget/SalesTableState"]
        self.sales_table.setColumnCount(8)
        self.sales_table.setHorizontalHeaderLabels(["販売日", "SKU", "商品名", "販売価格", "個数", "手数料", "利益", "返金総額"])
        # 右側の数値列で罫線が見えづらくならないよう明示設定
        self.sales_table.setShowGrid(True)
        self.sales_table.setGridStyle(Qt.SolidLine)
        layout.addWidget(self.sales_table)

    @staticmethod
    def _to_int_amount(value: Any, default: int = 0) -> int:
        """CSVの金額文字列を安全に整数化する。"""
        if value is None:
            return default
        text = str(value).strip()
        if not text or text.lower() in ("nan", "none"):
            return default
        text = text.replace(",", "")
        try:
            return int(round(float(text)))
        except Exception:
            return default

    @staticmethod
    def _to_int_count(value: Any, default: int = 1) -> int:
        """CSVの数量文字列を安全に整数化する。"""
        n = ProductWidget._to_int_amount(value, default=default)
        return n if n > 0 else default

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.lower() in ("nan", "none"):
            return ""
        return text

    def _build_sale_dedupe_key(self, sale: Dict[str, Any]) -> tuple:
        """重複取込判定用キー。"""
        order_id = self._normalize_text(sale.get("order_id"))
        sku = self._normalize_text(sale.get("sku"))
        if order_id and sku:
            return ("order_sku", order_id, sku)
        return (
            "fallback",
            sku,
            self._normalize_text(sale.get("sale_date")),
            self._to_int_amount(sale.get("sale_price"), default=0),
        )

    def _sync_purchase_status_from_sales(self) -> Dict[str, int]:
        """
        仕入DBと販売DBの数量を突き合わせてステータスを更新する。

        - 販売数量 >= 仕入数量: sold（販売済み）
        - 0 < 販売数量 < 仕入数量: partially_sold（一部販売済み）
        """
        summary = {
            "updated_sold": 0,
            "updated_partial": 0,
            "unchanged": 0,
            "target_skus": 0,
        }
        try:
            sales = self.sales_db.list_all()
        except Exception:
            return summary

        sold_qty_by_sku: Dict[str, int] = {}
        for sale in sales:
            sku = self._normalize_text(sale.get("sku"))
            if not sku:
                continue
            # Pending等は在庫減算に含めない（出荷済みのみを販売済みとして扱う）
            tx = self._normalize_text(sale.get("transaction_method")).lower()
            if tx and tx not in ("shipped", "shipped "):
                continue
            sold_qty_by_sku[sku] = sold_qty_by_sku.get(sku, 0) + self._to_int_count(sale.get("quantity"), default=1)

        summary["target_skus"] = len(sold_qty_by_sku)
        if not sold_qty_by_sku:
            return summary

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for sku, sold_qty in sold_qty_by_sku.items():
            purchase = self.purchase_history_db.get_by_sku(sku)
            if not purchase:
                continue

            purchase_qty = self._to_int_count(purchase.get("quantity"), default=1)
            current_status = self._normalize_text(purchase.get("status")).lower() or "ready"
            if current_status == "inventory_only":
                summary["unchanged"] += 1
                continue
            next_status = None
            reason = ""

            if sold_qty >= purchase_qty:
                next_status = "sold"
                reason = f"販売CSV連動: 販売数 {sold_qty} / 仕入数 {purchase_qty}"
            elif sold_qty > 0:
                next_status = "partially_sold"
                reason = f"販売CSV連動: 販売数 {sold_qty} / 仕入数 {purchase_qty}（在庫残あり）"

            if not next_status or current_status == next_status:
                summary["unchanged"] += 1
                continue

            self.purchase_history_db.upsert({
                "sku": sku,
                "status": next_status,
                "status_reason": reason,
                "status_set_at": now_str,
            })
            if next_status == "sold":
                summary["updated_sold"] += 1
            elif next_status == "partially_sold":
                summary["updated_partial"] += 1

        return summary

    def import_sales_csv(self):
        """売れたものCSVを販売DBへ取り込む。"""
        default_dir = self.settings.value("directories/sales_csv", "")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "販売CSVを選択",
            default_dir,
            "CSVファイル (*.csv);;すべてのファイル (*)"
        )
        if not file_path:
            return

        try:
            from utils.csv_io import csv_io

            df = csv_io.read_csv(file_path)
            if df is None or df.empty:
                QMessageBox.warning(self, "販売CSV取込", "CSVの読み込みに失敗したか、データが空です。")
                return

            required_cols = ["SKU", "注文日"]
            missing = [c for c in required_cols if c not in df.columns]
            if missing:
                QMessageBox.warning(
                    self,
                    "販売CSV取込",
                    f"必須列が不足しています: {', '.join(missing)}"
                )
                return

            selected_dir = str(Path(file_path).parent)
            self.settings.setValue("directories/sales_csv", selected_dir)

            existing_sales = self.sales_db.list_all()
            existing_by_key: Dict[tuple, Dict[str, Any]] = {}
            existing_keys = set()
            for s in existing_sales:
                key = self._build_sale_dedupe_key(s)
                existing_keys.add(key)
                # 同一キーが複数ある場合は先勝（通常は重複なし想定）
                if key not in existing_by_key:
                    existing_by_key[key] = s
            imported_keys = set()

            inserted = 0
            updated = 0
            skipped_duplicate = 0
            skipped_invalid = 0

            for _, row in df.iterrows():
                sku = self._normalize_text(row.get("SKU"))
                sale_date = self._normalize_text(row.get("注文日"))
                if not sku or not sale_date:
                    skipped_invalid += 1
                    continue

                sale_price = self._to_int_amount(row.get("販売価格"), default=0)
                if sale_price <= 0:
                    sale_price = self._to_int_amount(row.get("出品価格"), default=0)

                platform_fee = self._to_int_amount(
                    row.get(COL_PLATFORM_FEE) or row.get("Amazon手数料"),
                    default=0,
                )
                shipping_fee = self._to_int_amount(row.get("配送料"), default=0)
                quantity = self._to_int_count(row.get("売れた個数"), default=1)

                other_fees = (
                    self._to_int_amount(row.get("配送手数料"), default=0)
                    + self._to_int_amount(row.get("送料手数料"), default=0)
                    + self._to_int_amount(row.get("払い戻し手数料"), default=0)
                    + self._to_int_amount(row.get("返金手数料"), default=0)
                    + self._to_int_amount(row.get("ギフト包装チャージバック"), default=0)
                    + self._to_int_amount(row.get("その他"), default=0)
                )

                net_profit_raw = row.get("粗利益")
                net_profit = (
                    self._to_int_amount(net_profit_raw, default=None)
                    if net_profit_raw is not None and str(net_profit_raw).strip() != ""
                    else None
                )
                refund_total = self._to_int_amount(row.get("返金総額"), default=0)

                sale_payload = {
                    "sku": sku,
                    "sale_date": sale_date,
                    "sales_method": self._normalize_text(row.get("配送経路")) or "FBA",
                    "platform": "Amazon",
                    "sale_price": sale_price,
                    "quantity": quantity,
                    "title": self._normalize_text(row.get("商品名")),
                    "platform_fee": platform_fee,
                    "shipping_fee": shipping_fee,
                    "other_fees": other_fees,
                    "refund_total": refund_total,
                    "net_profit": net_profit,
                    "order_id": self._normalize_text(row.get("AmazonOrderId")),
                    "transaction_method": self._normalize_text(row.get("出荷状態")),
                }

                dedupe_key = self._build_sale_dedupe_key(sale_payload)
                existing_sale = existing_by_key.get(dedupe_key)
                if existing_sale is not None:
                    existing_price = self._to_int_amount(existing_sale.get("sale_price"), default=0)
                    incoming_price = self._to_int_amount(sale_payload.get("sale_price"), default=0)
                    # 未確定(0円) → 確定(>0円) のときは更新する
                    if existing_price <= 0 < incoming_price:
                        target_id = existing_sale.get("id")
                        if target_id:
                            self.sales_db.update(int(target_id), sale_payload)
                            updated += 1
                            # 以降の重複判定にも最新値を反映
                            existing_by_key[dedupe_key] = {**existing_sale, **sale_payload}
                            continue
                    skipped_duplicate += 1
                    continue

                if dedupe_key in imported_keys:
                    skipped_duplicate += 1
                    continue

                self.sales_db.insert(sale_payload)
                imported_keys.add(dedupe_key)
                inserted += 1

            status_sync = self._sync_purchase_status_from_sales()
            self.load_sales_data()
            try:
                # 仕入DB表示が開いている場合は、ステータス表示を最新化
                if hasattr(self, "purchase_all_records_master"):
                    base_records = copy.deepcopy(getattr(self, "purchase_all_records_master", []) or [])
                    if base_records:
                        self.load_purchase_data(base_records)
            except Exception:
                pass

            QMessageBox.information(
                self,
                "販売CSV取込完了",
                f"取込件数: {inserted} 件\n"
                f"更新件数(0円→確定): {updated} 件\n"
                f"重複スキップ: {skipped_duplicate} 件\n"
                f"不正データスキップ: {skipped_invalid} 件\n\n"
                f"ステータス更新（販売済み）: {status_sync.get('updated_sold', 0)} 件\n"
                f"ステータス更新（一部販売済み）: {status_sync.get('updated_partial', 0)} 件\n"
                f"ステータス変更なし: {status_sync.get('unchanged', 0)} 件"
            )
        except Exception as e:
            QMessageBox.critical(self, "販売CSV取込エラー", f"販売CSVの取込に失敗しました:\n{e}")

    def get_all_purchase_records(self) -> List[Dict[str, Any]]:
        """現在のすべての仕入レコードを返す"""
        return getattr(self, 'purchase_all_records', [])

    def load_products(self):
        """商品データを読み込み"""
        try:
            products = self.db.list_all()
            self.table.setRowCount(len(products))
            for i, product in enumerate(products):
                self.table.setItem(i, 0, QTableWidgetItem(product.get("sku") or ""))
                self.table.setItem(i, 1, QTableWidgetItem(product.get("product_name") or ""))
                # JANコードの.0を削除（表示用の正規化）
                jan_value = product.get("jan") or ""
                if jan_value:
                    jan_str = str(jan_value).strip()
                    # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
                    if jan_str.endswith(".0"):
                        jan_str = jan_str[:-2]
                else:
                    jan_str = ""
                self.table.setItem(i, 2, QTableWidgetItem(jan_str))
                self.table.setItem(i, 3, QTableWidgetItem(product.get("asin") or ""))
                self.table.setItem(i, 4, QTableWidgetItem(product.get("purchase_date") or ""))
                self.table.setItem(i, 5, QTableWidgetItem(str(product.get("purchase_price") or "")))
                self.table.setItem(i, 6, QTableWidgetItem(str(product.get("quantity") or "")))
                self.table.setItem(i, 7, QTableWidgetItem(product.get("store_code") or ""))
                self.table.setItem(i, 8, QTableWidgetItem(product.get("store_name") or ""))
                self.table.setItem(i, 9, QTableWidgetItem(str(product.get("warranty_period_days") or "")))
                self.table.setItem(i, 10, QTableWidgetItem(product.get("warranty_until") or ""))
                # 画像列
                for j in range(1, 7):
                    image_key = f"image_{j}"
                    image_path = product.get(image_key) or ""
                    # パスのみ表示
                    item = QTableWidgetItem(os.path.basename(image_path) if image_path else "")
                    item.setData(Qt.UserRole, image_path) # フルパスを保持
                    if image_path:
                        item.setToolTip(f"クリックして開く: {image_path}")
                        item.setForeground(Qt.white)  # 青色から白色に変更
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)
                    self.table.setItem(i, 10 + j, item)

            self.table.resizeColumnsToContents()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"商品データの読み込みに失敗しました:\n{e}")

    def on_add_product(self):
        dialog = ProductEditDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                try:
                    self.db.upsert(data)
                    self.load_products()
                except Exception as e:
                    QMessageBox.critical(self, "エラー", f"商品の追加に失敗しました:\n{e}")

    def on_edit_product(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "選択なし", "編集する商品を選択してください。")
            return
        
        sku_item = self.table.item(row, 0)
        sku = sku_item.text()
        
        try:
            product = self.db.get_by_sku(sku)
            if not product:
                QMessageBox.warning(self, "エラー", "商品データが見つかりません。")
                return
            
            dialog = ProductEditDialog(self, product)
            if dialog.exec_() == QDialog.Accepted:
                data = dialog.get_data()
                if data:
                    self.db.upsert(data)
                    self.load_products()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"商品データの取得に失敗しました:\n{e}")

    def on_delete_product(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "選択なし", "削除する商品を選択してください。")
            return
        
        sku_item = self.table.item(row, 0)
        sku = sku_item.text()
        
        if QMessageBox.question(self, "確認", f"SKU: {sku} を削除しますか？") == QMessageBox.Yes:
            try:
                self.db.delete(sku)
                self.load_products()
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"削除に失敗しました:\n{e}")

    def on_product_table_cell_clicked(self, row, col):
        """商品テーブルのセルクリック処理（画像を開く）"""
        # 画像列は11〜16
        if 11 <= col <= 16:
            item = self.table.item(row, col)
            if item:
                image_path = item.data(Qt.UserRole)
                if image_path and os.path.exists(image_path):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(image_path))

    def load_sales_data(self):
        """販売データを読み込み、販売DBタブに表示する。"""
        try:
            # sales テーブルから全販売情報を取得（新しい順）
            sales = self.sales_db.list_all()
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"販売データの読み込みに失敗しました:\n{e}")
            return

        self.sales_table.setRowCount(0)

        for row_idx, sale in enumerate(sales):
            self.sales_table.insertRow(row_idx)

            # 販売日
            sale_date = str(sale.get("sale_date") or "")
            self.sales_table.setItem(row_idx, 0, QTableWidgetItem(sale_date))

            # SKU
            sku = str(sale.get("sku") or "")
            sku_item = QTableWidgetItem(sku)
            self.sales_table.setItem(row_idx, 1, sku_item)

            # 商品名（product_db からSKUで引ければ商品名）
            product_name = ""
            try:
                product = self.db.get_by_sku(sku)
                if product:
                    product_name = str(product.get("product_name") or product.get("商品名") or "")
            except Exception:
                product = None
            # 商品名が取得できなかった場合は sales.title を利用、それも無ければSKUを表示
            if not product_name:
                title = sale.get("title") or ""
                if title:
                    product_name = str(title)
            if not product_name:
                product_name = sku
            item_name = QTableWidgetItem(product_name)
            # フルのSKUをUserRoleに保持しておく
            item_name.setData(Qt.UserRole, sku)
            self.sales_table.setItem(row_idx, 2, item_name)

            # 販売価格
            sale_price = sale.get("sale_price") or 0
            item_price = QTableWidgetItem(f"{sale_price:,}")
            item_price.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sales_table.setItem(row_idx, 3, item_price)

            # 個数
            quantity = sale.get("quantity") or 1
            item_qty = QTableWidgetItem(str(quantity))
            item_qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sales_table.setItem(row_idx, 4, item_qty)

            # 手数料（platform_fee + fba_fee + other_fees）
            fee_total = (sale.get("platform_fee") or 0) + (sale.get("fba_fee") or 0) + (sale.get("other_fees") or 0)
            item_fee = QTableWidgetItem(f"{fee_total:,}")
            item_fee.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sales_table.setItem(row_idx, 5, item_fee)

            # 利益（net_profit。なければ sale_price - 手数料）
            net_profit = sale.get("net_profit")
            if net_profit is None:
                net_profit = (sale_price or 0) - fee_total
            item_profit = QTableWidgetItem(f"{net_profit:,}")
            item_profit.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sales_table.setItem(row_idx, 6, item_profit)

            # 返金総額
            refund_total = sale.get("refund_total") or 0
            item_refund = QTableWidgetItem(f"{refund_total:,}")
            item_refund.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sales_table.setItem(row_idx, 7, item_refund)

            # 返金総額がある行は黄色背景で強調
            if self._to_int_amount(refund_total, default=0) != 0:
                refund_bg = QColor(255, 235, 120)
                for col in range(self.sales_table.columnCount()):
                    cell = self.sales_table.item(row_idx, col)
                    if cell:
                        cell.setBackground(refund_bg)

        self.sales_table.resizeColumnsToContents()
        self._sales_loaded = True

    def _calculate_product_name_width(self) -> int:
        return 300

