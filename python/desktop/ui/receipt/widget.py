#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""レシート管理ウィジェット（オーケストレーター）。"""
from __future__ import annotations

import os
import re
import sys
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea, QSizePolicy, QStyledItemDelegate,
    QSplitter, QListWidget, QListWidgetItem, QMenu,
    QFormLayout, QApplication, QCheckBox, QProgressDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings, QTimer, QUrl, QCoreApplication
from PySide6.QtGui import QPixmap, QTransform, QColor, QDesktopServices, QClipboard

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_evidence_completed

try:
    from services.receipt_service import ReceiptService
    from services.receipt_matching_service import ReceiptMatchingService
    from services.purchase_break_even import compute_break_even_for_record
    from services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
except Exception:
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
    from desktop.services.purchase_break_even import compute_break_even_for_record
    from desktop.services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from desktop.services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase
from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from database.product_db import ProductDatabase
from database.route_db import RouteDatabase

from .support import (
    ReceiptOCRThread,
    ReceiptSnapshotDialog,
    _RECEIPT_ACTION_TO_PIPELINE_STEP,
    _RECEIPT_WORKFLOW_PIPELINE_SEGMENTS,
    _format_receipt_status_prefix_html,
    _format_receipt_workflow_pipeline_html,
    AccountTitleDelegate,
    StoreNameDelegate,
    WarrantyProductDelegate,
)


from .snapshot_mixin import ReceiptSnapshotMixin
from .workflow_mixin import ReceiptWorkflowMixin
from .ocr_mixin import ReceiptOcrMixin
from .matching_mixin import ReceiptMatchingMixin
from .table_mixin import ReceiptTableMixin
from .gcs_mixin import ReceiptGcsMixin
from .rename_mixin import ReceiptRenameMixin
from .warranty_mixin import ReceiptWarrantyMixin
from .linkage_mixin import ReceiptLinkageMixin

class ReceiptWidget(
    ReceiptSnapshotMixin,
    ReceiptWorkflowMixin,
    ReceiptOcrMixin,
    ReceiptMatchingMixin,
    ReceiptTableMixin,
    ReceiptGcsMixin,
    ReceiptRenameMixin,
    ReceiptWarrantyMixin,
    ReceiptLinkageMixin,
    QWidget,
):
    """レシート管理ウィジェット"""

    receipt_processed = Signal(dict)

    def __init__(self, api_client=None, inventory_widget=None):
        super().__init__()
        self.api_client = api_client
        self.inventory_widget = inventory_widget
        self.product_widget = None  # ProductWidgetへの参照
        self.receipt_service = ReceiptService()
        self.matching_service = ReceiptMatchingService()
        self.receipt_db = ReceiptDatabase()
        self.inventory_db = InventoryDatabase()
        self.store_db = StoreDatabase()
        self.account_title_db = AccountTitleDatabase()
        self.route_db = RouteDatabase()
        # レシート一覧用スナップショット保存先ディレクトリ
        try:
            # ui/receipt/widget.py → parents[3] = python/（分割前 ui/receipt_widget.py の parents[2] と同じ）
            base_dir = Path(__file__).resolve().parents[3]
            self.receipt_snapshot_dir = base_dir / "data" / "receipt_snapshots"
            self.receipt_snapshot_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.receipt_snapshot_dir = None

        # フォルダ一括OCR用
        self.current_folder: Optional[Path] = None
        self.ocr_queue: List[str] = []
        self.batch_running: bool = False
        self.batch_total_count: int = 0  # 一括OCR処理の全体件数
        self.batch_processed_count: int = 0  # 一括OCR処理の処理済み件数
        self._store_name_cache: dict[str, str] = {}
        self.current_receipt_id = None
        self.current_receipt_data = None
        self.notifications_enabled = True
        # レシート一覧の初回ロードが完了しているかどうか
        self._initial_data_loaded: bool = False
        # 確定処理の多重起動防止フラグ
        self._confirm_in_progress: bool = False
        # 日付自動修復で「いいえ」を選んだレシートID（同一セッションで再確認しない）
        self._date_repair_declined_ids: set[int] = set()
        self._workflow_status_text = "ワークフロー: 未実行"
        self._workflow_emphasize = False
        self._workflow_active_step: Optional[int] = None
        self._workflow_post_step: Optional[int] = None
        # ⑤一括リネーム完了後のみ ⑦GCS / ⑧確定 を許可
        self._bulk_rename_completed: bool = False
        self._gcs_upload_completed: bool = False
        
        self.setup_ui()
        
        # デフォルトフォルダを読み込み（UI構築後に実行）
        self.load_default_folder()
        # 初期フォルダラベルを更新
        if hasattr(self, 'folder_label'):
            self.update_folder_label()

        # テーブルの列幅を復元
        restore_table_header_state(self.receipt_table, "ReceiptWidget/ReceiptTableHeaderState")
        restore_table_header_state(self.warranty_table, "ReceiptWidget/WarrantyTableHeaderState")

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
        for attr in (
            "receipt_db",
            "inventory_db",
            "store_db",
            "account_title_db",
            "route_db",
        ):
            self._close_db_connection(getattr(self, attr, None))
        self.receipt_db = ReceiptDatabase()
        self.inventory_db = InventoryDatabase()
        self.store_db = StoreDatabase()
        self.account_title_db = AccountTitleDatabase()
        self.route_db = RouteDatabase()
        self.current_receipt_id = None
        self.current_receipt_data = None
        self._initial_data_loaded = False
    
    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.receipt_table, "ReceiptWidget/ReceiptTableHeaderState")
        save_table_header_state(self.warranty_table, "ReceiptWidget/WarrantyTableHeaderState")
        
        # スプリッターの状態を即座に保存（タイマーを待たずに）
        if hasattr(self, 'receipt_splitter'):
            try:
                s = QSettings("HIRIO", "SedoriDesktopApp")
                sizes = self.receipt_splitter.sizes()
                if len(sizes) >= 2:
                    s.setValue("receipt/splitter_receipt_height", sizes[0])
                    s.setValue("receipt/splitter_warranty_height", sizes[1])
            except Exception as e:
                print(f"レシートスプリッター状態保存エラー: {e}")
    
    def set_product_widget(self, product_widget):
        """ProductWidgetへの参照を設定"""
        self.product_widget = product_widget

    def _ensure_product_widget_data_loaded(self) -> None:
        """
        データベース管理タブを開かなくても仕入DB（purchase_all_records）を参照できるようにする。
        ProductWidget は showEvent で初回読み込みするため、証憑管理だけ先に使うと空になる。
        """
        if not self.product_widget:
            return
        try:
            self.product_widget.ensure_initial_data_loaded()
        except Exception as e:
            logger.warning("仕入DBの先行読み込みに失敗しました: %s", e)

    def _get_purchase_records(self) -> List[Dict[str, Any]]:
        """仕入DBレコード一覧（必要なら先行読み込みしてから返す）"""
        if not self.product_widget:
            return []
        self._ensure_product_widget_data_loaded()
        if hasattr(self.product_widget, "get_all_purchase_records"):
            return self.product_widget.get_all_purchase_records() or []
        return getattr(self.product_widget, "purchase_all_records", []) or []
    
    def set_evidence_widget(self, evidence_widget):
        """EvidenceManagerWidgetへの参照を設定"""
        self.evidence_widget = evidence_widget

    def _get_current_receipts_from_tables(self) -> List[Dict[str, Any]]:
        """
        現在のレシート一覧・保証書一覧に表示されている行に対応する
        ReceiptDatabaseレコードを取得するヘルパー。
        過去全件ではなく「今この画面で扱っている対象」に限定するために使用する。
        """
        receipt_ids: set[int] = set()

        # レシート一覧テーブルからIDを収集
        table = getattr(self, "receipt_table", None)
        if table is not None:
            for row in range(table.rowCount()):
                item = table.item(row, 0)  # ID(内部)列
                if not item:
                    continue
                text = (item.text() or "").strip()
                if not text:
                    continue
                try:
                    rid = int(text)
                except ValueError:
                    continue
                receipt_ids.add(rid)

        # 保証書一覧テーブルからもIDを収集（同じreceiptsテーブルを参照）
        warranty_table = getattr(self, "warranty_table", None)
        if warranty_table is not None:
            for row in range(warranty_table.rowCount()):
                item = warranty_table.item(row, 0)  # ID(内部)列
                if not item:
                    continue
                text = (item.text() or "").strip()
                if not text:
                    continue
                try:
                    rid = int(text)
                except ValueError:
                    continue
                receipt_ids.add(rid)

        receipts: List[Dict[str, Any]] = []
        for rid in receipt_ids:
            try:
                rec = self.receipt_db.get_receipt(rid)
            except Exception:
                rec = None
            if rec:
                receipts.append(rec)
        return receipts

    # ==================== レシート一覧スナップショット（検証用） ====================

    def setup_ui(self):
        """UIの設定（シンプルなレイアウト）"""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # 処理実行エリア
        self.setup_action_section()
        
        # レシート一覧
        self.setup_receipt_list_simple()
        
        # スプリッターでエリアの高さを調整可能にする
        self.setup_receipt_splitter()
    
    def setup_upload_section(self):
        """画像アップロードセクション"""
        upload_group = QGroupBox("レシート画像アップロード")
        upload_layout = QVBoxLayout(upload_group)
        self.upload_group = upload_group
        
        btn_layout = QHBoxLayout()

        # フォルダ選択ボタン（フォルダ内の全画像を一括OCR）
        self.folder_btn = QPushButton("フォルダ選択")
        self.folder_btn.clicked.connect(self.select_folder_for_batch)
        btn_layout.addWidget(self.folder_btn)

        # 単一画像選択ボタン
        self.upload_btn = QPushButton("画像を選択")
        self.upload_btn.clicked.connect(self.select_image)
        self.upload_btn.setStyleSheet("""
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
        """)
        btn_layout.addWidget(self.upload_btn)

        # 全件OCRボタン（選択フォルダ内の全画像を順番に処理）
        self.batch_btn = QPushButton("全件OCR")
        self.batch_btn.clicked.connect(self.start_batch_ocr)
        btn_layout.addWidget(self.batch_btn)

        btn_layout.addStretch()
        upload_layout.addLayout(btn_layout)
        
        self.image_path_label = QLabel("画像未選択")
        upload_layout.addWidget(self.image_path_label)
        
        self.layout.addWidget(upload_group)
    
    
    def setup_action_section(self):
        """ファイル操作・アクション（ワークフロー付き）"""
        action_group = QGroupBox("ファイル操作・アクション")
        action_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        action_outer = QVBoxLayout(action_group)
        action_outer.setSpacing(4)
        action_outer.setContentsMargins(5, 5, 5, 5)

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

        action_layout = QHBoxLayout()
        action_layout.setSpacing(5)

        self.folder_btn = QPushButton("フォルダ選択")
        self.folder_btn.clicked.connect(
            lambda: self._run_action_with_status("フォルダ選択", self.select_folder_for_batch)
        )
        self.folder_btn.setStyleSheet(green_button_style)

        self.batch_btn = QPushButton("全件OCR")
        self.batch_btn.clicked.connect(
            lambda: self._run_action_with_status("全件OCR", self.start_batch_ocr)
        )
        self.batch_btn.setStyleSheet(green_button_style)

        self.bulk_match_btn = QPushButton("一括マッチング")
        self.bulk_match_btn.clicked.connect(
            lambda: self._run_action_with_status("一括マッチング", self.bulk_match_receipts)
        )
        self.bulk_match_btn.setStyleSheet(green_button_style)

        self.bulk_rename_btn = QPushButton("一括リネーム")
        self.bulk_rename_btn.clicked.connect(
            lambda: self._run_action_with_status("一括リネーム", self.bulk_rename_receipts)
        )
        self.bulk_rename_btn.setStyleSheet(green_button_style)

        self.verify_btn = QPushButton("照合チェック")
        self.verify_btn.clicked.connect(
            lambda: self._run_action_with_status("照合チェック", self.verify_receipts_with_purchases)
        )
        self.verify_btn.setStyleSheet(green_button_style)

        self.gcs_upload_btn = QPushButton("GCSアップロード")
        self.gcs_upload_btn.setToolTip("レシート一覧の全件をGCSにアップロードします")
        self.gcs_upload_btn.clicked.connect(
            lambda: self._run_action_with_status("GCSアップロード", self.show_gcs_upload_dialog)
        )
        self.gcs_upload_btn.setStyleSheet(green_button_style)

        self.confirm_btn = QPushButton("確定")
        self.confirm_btn.clicked.connect(
            lambda: self._run_action_with_status("確定", self.confirm_receipt_linkage)
        )
        self.confirm_btn.setStyleSheet(green_button_style)

        action_layout.addWidget(self.folder_btn)
        action_layout.addWidget(self.batch_btn)
        action_layout.addWidget(self.bulk_match_btn)
        action_layout.addWidget(self.bulk_rename_btn)
        action_layout.addWidget(self.verify_btn)
        action_layout.addWidget(self.gcs_upload_btn)
        action_layout.addWidget(self.confirm_btn)
        action_layout.addStretch()

        self.delete_all_btn = QPushButton("クリア")
        self.delete_all_btn.clicked.connect(self.delete_all_receipts)
        action_layout.addWidget(self.delete_all_btn)

        self.default_folder_btn = QPushButton("デフォルトフォルダ設定")
        self.default_folder_btn.setToolTip("処理の起点となるデフォルトフォルダを設定します")
        self.default_folder_btn.clicked.connect(self.set_default_folder)
        action_layout.addWidget(self.default_folder_btn)

        action_outer.addLayout(action_layout)

        self.workflow_status_label = QLabel()
        self.workflow_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_status_label.setWordWrap(True)
        self.workflow_status_label.setStyleSheet("padding: 2px 0px;")
        self._sync_workflow_status_label()
        action_outer.addWidget(self.workflow_status_label)

        aux_layout = QHBoxLayout()
        self.process_btn = QPushButton("OCR処理")
        self.process_btn.setToolTip("フォルダ選択後、キューの先頭1枚だけOCR処理します")
        self.process_btn.clicked.connect(self.process_selected_file)
        aux_layout.addWidget(self.process_btn)

        self.save_receipt_snapshot_btn = QPushButton("スナップ保存")
        self.save_receipt_snapshot_btn.setToolTip("現在のレシート一覧を一時保存します（検証用）")
        self.save_receipt_snapshot_btn.clicked.connect(self.save_receipt_snapshot)
        aux_layout.addWidget(self.save_receipt_snapshot_btn)

        self.load_receipt_snapshot_btn = QPushButton("スナップ読込")
        self.load_receipt_snapshot_btn.setToolTip("前回保存したレシート一覧スナップショットを読み込みます（検証用）")
        self.load_receipt_snapshot_btn.clicked.connect(self.load_receipt_snapshot)
        aux_layout.addWidget(self.load_receipt_snapshot_btn)

        self.delete_row_btn = QPushButton("選択行削除")
        self.delete_row_btn.setEnabled(False)
        self.delete_row_btn.clicked.connect(self.delete_selected_receipts)
        aux_layout.addWidget(self.delete_row_btn)
        aux_layout.addStretch()
        action_outer.addLayout(aux_layout)

        self.layout.addWidget(action_group)
        self._reset_post_rename_workflow_gate()

    def setup_receipt_list_simple(self):
        """レシート一覧セクション（シンプル版）"""
        list_group = QGroupBox("レシート一覧")
        list_layout = QVBoxLayout(list_group)

        self.receipt_table = QTableWidget()
        # 0列目のIDは非表示（内部用）、1列目に種別、2列目に科目、3列目に画像ファイル名
        # 「登録番号」カラムを追加（店舗マスタと同様の登録番号T+13桁）
        # 「レシート画像URL」カラムを追加（SKUの右、GCSアップロード時のURLを表示）
        self.receipt_table.setColumnCount(13)
        self.receipt_table.setHorizontalHeaderLabels([
            "ID(内部)", "種別", "科目", "画像ファイル名", "日付",
            "店舗名", "電話番号", "合計", "差額", "店舗コード", "登録番号", "SKU", "レシート画像URL"
        ])
        self.receipt_table.horizontalHeader().setStretchLastSection(True)
        self.receipt_table.itemDoubleClicked.connect(self.on_receipt_double_clicked)
        self.receipt_table.itemSelectionChanged.connect(self.on_receipt_selection_changed)
        # 右クリックメニューを有効化
        self.receipt_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.receipt_table.customContextMenuRequested.connect(self.on_receipt_table_context_menu)
        list_layout.addWidget(self.receipt_table)

        # ID列はユーザーには見せない
        self.receipt_table.setColumnHidden(0, True)

        # 「科目」列はコンボボックスで編集（通常時はテキストだけ表示される）
        self.account_title_delegate = AccountTitleDelegate(
            self.receipt_table, self.receipt_db, self.account_title_db
        )
        self.receipt_table.setItemDelegateForColumn(2, self.account_title_delegate)
        
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_receipt_splitter()で追加される
        self.receipt_list_group = list_group

        # 保証書一覧エリア
        warranty_group = QGroupBox("保証書一覧")
        warranty_layout = QVBoxLayout(warranty_group)

        # 保証書一覧の操作ボタン
        warranty_action_layout = QHBoxLayout()
        self.delete_warranty_row_btn = QPushButton("選択行削除")
        self.delete_warranty_row_btn.setEnabled(False)
        self.delete_warranty_row_btn.clicked.connect(self.delete_selected_warranties)
        warranty_action_layout.addWidget(self.delete_warranty_row_btn)
        warranty_action_layout.addStretch()
        warranty_layout.addLayout(warranty_action_layout)

        self.warranty_table = QTableWidget()
        # 0列目は内部ID、ユーザーには非表示
        self.warranty_table.setColumnCount(11)
        self.warranty_table.setHorizontalHeaderLabels([
            "ID(内部)", "種別", "画像ファイル名", "日付",
            "店舗名", "電話番号", "店舗コード", "SKU", "商品名", "保証期間(日)", "保証最終日"
        ])
        self.warranty_table.horizontalHeader().setStretchLastSection(True)
        self.warranty_table.setColumnHidden(0, True)
        # 保証期間編集時の処理
        self.warranty_table.cellChanged.connect(self.on_warranty_cell_changed)
        # 画像名ダブルクリックで拡大表示
        self.warranty_table.itemDoubleClicked.connect(self.on_warranty_item_double_clicked)
        # コンテキストメニューを有効化
        self.warranty_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.warranty_table.customContextMenuRequested.connect(self.on_warranty_table_context_menu)
        # 選択変更時にボタンの有効/無効を切り替え
        self.warranty_table.itemSelectionChanged.connect(self.on_warranty_selection_changed)
        warranty_layout.addWidget(self.warranty_table)

        # スプリッターで管理するため、固定高さの設定を削除
        # スプリッターで管理するため、ここではレイアウトに追加しない
        # setup_receipt_splitter()で追加される
        self.warranty_list_group = warranty_group

        # 照合チェック情報表示エリア
        info_group = QGroupBox("照合チェック情報")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(5, 5, 5, 5)
        info_layout.setSpacing(2)
        self.verification_info_text = QTextEdit()
        self.verification_info_text.setReadOnly(True)
        self.verification_info_text.setFixedHeight(50)
        self.verification_info_text.setPlaceholderText("照合チェックボタンをクリックすると、レシートと仕入DBの照合結果が表示されます。")
        info_layout.addWidget(self.verification_info_text)
        self.layout.addWidget(info_group)
        # 起動直後はレシート一覧を読み込まず、
        # タブが実際に表示されたタイミングで初回ロードを行う
    
    def setup_receipt_splitter(self):
        """スプリッターでレシート一覧と保証書一覧の高さを調整可能にする"""
        # スプリッターを作成（縦方向）
        self.receipt_splitter = QSplitter(Qt.Vertical)
        
        # エリアをスプリッターに追加
        self.receipt_splitter.addWidget(self.receipt_list_group)
        self.receipt_splitter.addWidget(self.warranty_list_group)
        
        # 初期の高さ比率を設定（レシート一覧: 保証書一覧 = 3:1）
        self.receipt_splitter.setStretchFactor(0, 3)  # レシート一覧
        self.receipt_splitter.setStretchFactor(1, 1)  # 保証書一覧
        
        # スプリッターの状態変更を監視して保存
        self.receipt_splitter.splitterMoved.connect(self.save_receipt_splitter_state)
        
        # レイアウトに追加（照合チェック情報の前に挿入）
        # レシート一覧と保証書一覧が既にレイアウトに追加されている場合は削除
        layout = self.layout
        receipt_index = -1
        warranty_index = -1
        info_group_index = -1
        
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if widget == self.receipt_list_group:
                    receipt_index = i
                elif widget == self.warranty_list_group:
                    warranty_index = i
                elif isinstance(widget, QGroupBox) and widget.title() == "照合チェック情報":
                    info_group_index = i
        
        # 既に追加されている場合は削除
        if receipt_index >= 0:
            layout.removeWidget(self.receipt_list_group)
        if warranty_index >= 0:
            layout.removeWidget(self.warranty_list_group)
        
        # スプリッターを照合チェック情報の前に挿入
        if info_group_index >= 0:
            layout.insertWidget(info_group_index, self.receipt_splitter, 1)  # stretch factor = 1
        else:
            # 見つからない場合は最後に追加
            layout.addWidget(self.receipt_splitter, 1)  # stretch factor = 1
        
        # ウィンドウが表示された後にスプリッターの状態を復元
        restore_timer = QTimer()
        restore_timer.setSingleShot(True)
        restore_timer.timeout.connect(self.restore_receipt_splitter_state)
        restore_timer.start(100)  # 100ms後に復元

    def ensure_initial_data_loaded(self) -> None:
        """
        レシート一覧・保証書一覧の初回読み込みを遅延実行する。
        起動時ではなく、タブが実際に表示されたタイミングで呼び出す。
        """
        if self._initial_data_loaded:
            return
        self.refresh_receipt_list()
        self._initial_data_loaded = True

    def showEvent(self, event):
        """
        ウィジェットがタブとして表示されたタイミングで初回ロードを行う。
        """
        super().showEvent(event)
        try:
            self.ensure_initial_data_loaded()
        except Exception as e:
            logger.warning(f"ReceiptWidget initial load error: {e}")
    
    def save_receipt_splitter_state(self):
        """スプリッターの状態を保存（デバウンス処理付き）"""
        # 頻繁に呼ばれるので、少し遅延させてから保存
        if not hasattr(self, '_receipt_splitter_save_timer'):
            self._receipt_splitter_save_timer = QTimer()
            self._receipt_splitter_save_timer.setSingleShot(True)
            def _batched_save():
                try:
                    s = QSettings("HIRIO", "SedoriDesktopApp")
                    # スプリッターの各エリアのサイズを保存
                    sizes = self.receipt_splitter.sizes()
                    if len(sizes) >= 2:
                        s.setValue("receipt/splitter_receipt_height", sizes[0])
                        s.setValue("receipt/splitter_warranty_height", sizes[1])
                except Exception as e:
                    print(f"レシートスプリッター状態保存エラー: {e}")
            self._receipt_splitter_save_timer.timeout.connect(_batched_save)
        
        # タイマーをリセット（500ms後に保存）
        self._receipt_splitter_save_timer.stop()
        self._receipt_splitter_save_timer.start(500)
    
    def restore_receipt_splitter_state(self):
        """スプリッターの状態を復元"""
        try:
            s = QSettings("HIRIO", "SedoriDesktopApp")
            receipt_height = s.value("receipt/splitter_receipt_height", None, type=int)
            warranty_height = s.value("receipt/splitter_warranty_height", None, type=int)
            
            if receipt_height is not None and warranty_height is not None and receipt_height > 0 and warranty_height > 0:
                # 保存されたサイズを復元
                self.receipt_splitter.setSizes([receipt_height, warranty_height])
            else:
                # デフォルトの比率を設定（レシート一覧: 保証書一覧 = 3:1）
                # 実際のサイズはウィンドウサイズに応じて自動調整される
                pass
        except Exception as e:
            print(f"レシートスプリッター状態復元エラー: {e}")
    
    def load_store_codes(self):
        """店舗コード候補を読み込み（店舗マスタ＋経費先）"""
        if not hasattr(self, 'store_code_combo'):
            return
        self.store_code_combo.clear()
        stores = self.store_db.list_stores()
        for store in stores:
            code = store.get('store_code') or store.get('supplier_code')
            name = store.get('store_name')
            if code:
                self.store_code_combo.addItem(f"{code} - {name}", code)
        dests = self.store_db.list_expense_destinations()
        for d in dests:
            code = (d.get('code') or '').strip()
            name = d.get('name') or ''
            if code:
                self.store_code_combo.addItem(f"{code} - {name}", code)
    
    def set_notifications_enabled(self, enabled: bool):
        """OCR完了・エラー時のメッセージ表示を制御"""
        self.notifications_enabled = enabled
    
    def reset_form(self):
        """フォームをリセット"""
        self.current_receipt_id = None
        self.current_receipt_data = None
        if hasattr(self, 'date_edit'):
            self.date_edit.setDate(QDate.currentDate())
        if hasattr(self, 'time_edit'):
            self.time_edit.clear()
        if hasattr(self, 'store_name_edit'):
            self.store_name_edit.clear()
        if hasattr(self, 'phone_edit'):
            self.phone_edit.clear()
        if hasattr(self, 'total_edit'):
            self.total_edit.clear()
        if hasattr(self, 'discount_edit'):
            self.discount_edit.clear()
        if hasattr(self, 'plastic_bag_edit'):
            self.plastic_bag_edit.clear()
        if hasattr(self, 'store_code_combo'):
            self.store_code_combo.clear()
        if hasattr(self, 'match_result_label'):
            self.match_result_label.clear()
        if hasattr(self, 'match_btn'):
            self.match_btn.setEnabled(False)
        if hasattr(self, 'view_image_btn'):
            self.view_image_btn.setEnabled(False)

