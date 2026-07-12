#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""単品仕入入力ダイアログ。"""
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

class SinglePurchaseInputDialog(QDialog):
    """単品仕入のひな型入力ダイアログ（実店舗/電脳/フリマを共通入力）"""

    SOURCE_TYPE_OPTIONS = ["実店舗", "電脳", "フリマ"]
    SOURCE_CHANNEL_PRESETS = ["Amazon", "楽天", "ヤフショ", "メルカリ", "ヤフオク", "問屋A"]
    CONDITION_PRESETS = ["新品", "中古(ほぼ新品)", "中古(非常に良い)", "中古(良い)", "中古(可)"]

    def __init__(self, condition_template_db, get_condition_key_func, inventory_widget=None, parent=None):
        super().__init__(parent)
        self.condition_template_db = condition_template_db
        self.get_condition_key = get_condition_key_func
        self._inventory_widget = inventory_widget
        self.store_db = StoreDatabase()
        self.keepa_service = KeepaService()
        self.ocr_service = OCRService()
        self.setWindowTitle("単品仕入入力（ひな型）")
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        # Windows環境で編集可能コンボの選択時に
        # 「白背景 + 白文字」になるケースを回避するため、ダイアログ内で明示指定する。
        self.setStyleSheet(
            """
            QLineEdit, QAbstractSpinBox, QDateEdit, QPlainTextEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #2d7dff;
                selection-color: #ffffff;
            }
            QLineEdit:focus, QAbstractSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #5aa2ff;
            }
            QComboBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #2d7dff;
                selection-color: #ffffff;
            }
            QComboBox QAbstractItemView {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                selection-background-color: #0078d4;
                selection-color: #ffffff;
            }
            QComboBox QLineEdit {
                background-color: #3c3c3c;
                color: #ffffff;
                selection-background-color: #2d7dff;
                selection-color: #ffffff;
            }
            """
        )

        main_layout = QVBoxLayout(self)
        self._splitter = QSplitter(Qt.Horizontal)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_panel = QWidget()
        layout = QFormLayout(left_panel)

        self.purchase_date_edit = QDateEdit()
        self.purchase_date_edit.setCalendarPopup(True)
        self.purchase_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.purchase_date_edit.setDate(QDate.currentDate())
        layout.addRow("仕入れ日:", self.purchase_date_edit)

        self.source_type_combo = QComboBox()
        self.source_type_combo.addItems(self.SOURCE_TYPE_OPTIONS)
        layout.addRow("仕入種別:", self.source_type_combo)

        self.source_channel_combo = QComboBox()
        self.source_channel_combo.setEditable(True)
        self.source_channel_combo.addItems(self.SOURCE_CHANNEL_PRESETS)
        self.source_channel_combo.currentTextChanged.connect(self._on_source_channel_changed)
        layout.addRow("仕入チャネル:", self.source_channel_combo)

        self.source_supplier_combo = QComboBox()
        self.source_supplier_combo.setEditable(False)
        self.source_supplier_combo.currentIndexChanged.connect(self._on_source_supplier_changed)
        layout.addRow("仕入先候補:", self.source_supplier_combo)

        self.order_id_edit = QLineEdit()
        self.order_id_edit.setPlaceholderText("注文番号（任意）")
        layout.addRow("注文番号:", self.order_id_edit)

        self.store_code_edit = QLineEdit()
        self.store_code_edit.setPlaceholderText("実店舗なら店舗コード、電脳/フリマなら空欄でも可")
        layout.addRow("店舗コード:", self.store_code_edit)

        self.asin_edit = QLineEdit()
        self.asin_edit.setPlaceholderText("ASIN")
        self.asin_edit.editingFinished.connect(self._on_asin_editing_finished)
        asin_row = QWidget()
        asin_row_layout = QHBoxLayout(asin_row)
        asin_row_layout.setContentsMargins(0, 0, 0, 0)
        asin_row_layout.addWidget(self.asin_edit)
        self.keepa_fill_btn = QPushButton("Keepa補完")
        self.keepa_fill_btn.setToolTip("ASINからKeepa情報を取得してJANと商品名を補完します")
        self.keepa_fill_btn.clicked.connect(self._fill_from_keepa_button_clicked)
        asin_row_layout.addWidget(self.keepa_fill_btn)
        layout.addRow("ASIN:", asin_row)

        self.jan_edit = QLineEdit()
        self.jan_edit.setPlaceholderText("JAN（任意）")
        layout.addRow("JAN:", self.jan_edit)

        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("SKU（空欄は未実装。右のボタンで生成）")
        sku_row = QWidget()
        sku_row_layout = QHBoxLayout(sku_row)
        sku_row_layout.setContentsMargins(0, 0, 0, 0)
        sku_row_layout.addWidget(self.sku_edit)
        self.generate_sku_btn = QPushButton("SKU生成")
        self.generate_sku_btn.setToolTip(
            "仕入データタブの「SKU生成」と同じ処理です（商品DBの重複照合・店舗マスタ・SKU日付・自己発送時の末尾M）。"
        )
        self.generate_sku_btn.clicked.connect(self._on_generate_sku_clicked)
        self.generate_sku_btn.setStyleSheet(
            """
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
        )
        sku_row_layout.addWidget(self.generate_sku_btn)
        layout.addRow("SKU:", sku_row)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("商品名")
        layout.addRow("商品名:", self.title_edit)

        self.condition_combo = QComboBox()
        self.condition_combo.setEditable(True)
        self.condition_combo.addItems(self.CONDITION_PRESETS)
        self.condition_combo.setCurrentText("中古(良い)")
        layout.addRow("コンディション:", self.condition_combo)

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setRange(1, 999)
        self.quantity_spin.setValue(1)
        layout.addRow("仕入れ個数:", self.quantity_spin)

        self.purchase_price_spin = QSpinBox()
        self.purchase_price_spin.setRange(0, 10_000_000)
        self.purchase_price_spin.setSingleStep(100)
        layout.addRow("仕入れ価格:", self.purchase_price_spin)

        self.planned_price_spin = QSpinBox()
        self.planned_price_spin.setRange(0, 10_000_000)
        self.planned_price_spin.setSingleStep(100)
        layout.addRow("販売予定価格:", self.planned_price_spin)

        self.shipping_combo = QComboBox()
        self.shipping_combo.addItems(SHIPPING_METHOD_OPTIONS)
        self.shipping_combo.setCurrentText("FBA")
        layout.addRow("発送方法:", self.shipping_combo)

        self.sales_channel_combo = QComboBox()
        self.sales_channel_combo.addItems(SALES_CHANNEL_OPTIONS)
        self.sales_channel_combo.setCurrentText("Amazon")
        layout.addRow("販売チャネル:", self.sales_channel_combo)

        self.amazon_fee_spin = QSpinBox()
        self.amazon_fee_spin.setRange(0, 10_000_000)
        self.amazon_fee_spin.setSingleStep(10)
        layout.addRow("プラットフォーム手数料:", self.amazon_fee_spin)

        self.shipping_cost_spin = QSpinBox()
        self.shipping_cost_spin.setRange(0, 10_000_000)
        self.shipping_cost_spin.setSingleStep(10)
        layout.addRow("出荷費用:", self.shipping_cost_spin)

        self.storage_fee_spin = QSpinBox()
        self.storage_fee_spin.setRange(0, 10_000_000)
        self.storage_fee_spin.setSingleStep(10)
        layout.addRow("在庫保管手数料:", self.storage_fee_spin)

        fee_action_row = QWidget()
        fee_action_layout = QHBoxLayout(fee_action_row)
        fee_action_layout.setContentsMargins(0, 0, 0, 0)
        self.open_fba_simulator_btn = QPushButton("FBA料金シミュレーターを開く")
        self.open_fba_simulator_btn.clicked.connect(self._open_fba_simulator_url)
        fee_action_layout.addWidget(self.open_fba_simulator_btn)
        self.ocr_fee_btn = QPushButton("貼り付けOCRで手数料読込")
        self.ocr_fee_btn.setToolTip(
            "コピー済みスクリーンショットをクリップボードから読み取ります（画像が無い場合はファイル選択）。"
            "「Amazonから出荷」「出品者出荷」で発送方法（FBA/自己発送）、"
            "「商品価格」は販売予定価格、手数料系は各欄に反映します。"
        )
        self.ocr_fee_btn.clicked.connect(self._load_fees_from_image_ocr)
        fee_action_layout.addWidget(self.ocr_fee_btn)
        layout.addRow("", fee_action_row)

        self.condition_note_edit = QPlainTextEdit()
        self.condition_note_edit.setMinimumHeight(70)
        self.condition_note_edit.setPlaceholderText("コンディション説明（任意）")
        layout.addRow("コンディション説明:", self.condition_note_edit)

        self.missing_manual_checkbox = QCheckBox("取説欠品")
        self.missing_inner_box_checkbox = QCheckBox("内箱欠品")
        self.missing_custom1_checkbox = QCheckBox("カスタム1")
        self.missing_custom2_checkbox = QCheckBox("カスタム2")
        self.missing_custom3_checkbox = QCheckBox("カスタム3")
        _missing_cb_style = """
                QCheckBox {
                    background-color: #3c3c3c;
                    color: #ffffff;
                    font-weight: bold;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 2px 8px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                }
            """
        for cb in (
            self.missing_manual_checkbox,
            self.missing_inner_box_checkbox,
            self.missing_custom1_checkbox,
            self.missing_custom2_checkbox,
            self.missing_custom3_checkbox,
        ):
            cb.setStyleSheet(_missing_cb_style)
        self._apply_custom_missing_checkbox_labels()
        self.missing_manual_checkbox.toggled.connect(self._sync_missing_custom_checkboxes_enabled)
        self.missing_inner_box_checkbox.toggled.connect(self._sync_missing_custom_checkboxes_enabled)

        missing_opts = QWidget()
        missing_opts_layout = QVBoxLayout(missing_opts)
        missing_opts_layout.setContentsMargins(0, 0, 0, 0)
        row1 = QHBoxLayout()
        row1.addWidget(self.missing_manual_checkbox)
        row1.addWidget(self.missing_inner_box_checkbox)
        row1.addStretch()
        missing_opts_layout.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(self.missing_custom1_checkbox)
        row2.addWidget(self.missing_custom2_checkbox)
        row2.addWidget(self.missing_custom3_checkbox)
        row2.addStretch()
        missing_opts_layout.addLayout(row2)
        layout.addRow("欠品・詳細（選択）:", missing_opts)

        self.call_condition_note_btn = QPushButton("コンディション説明呼び出し")
        self.call_condition_note_btn.setToolTip("選択したコンディションに対応する説明をコンディション説明タブから読み込みます")
        self.call_condition_note_btn.clicked.connect(self._on_call_condition_note)
        layout.addRow("", self.call_condition_note_btn)

        self.comment_edit = QPlainTextEdit()
        self.comment_edit.setMinimumHeight(80)
        self.comment_edit.setPlaceholderText("メモ（任意）")
        layout.addRow("コメント:", self.comment_edit)

        left_scroll.setWidget(left_panel)
        self._splitter.addWidget(left_scroll)

        self._channel_detail_widget = QWidget()
        self._channel_detail_widget.setMinimumWidth(300)
        ch_outer = QVBoxLayout(self._channel_detail_widget)
        self._channel_detail_title = QLabel()
        self._channel_detail_title.setWordWrap(True)
        self._channel_detail_title.setStyleSheet("font-weight: bold; padding: 4px 0;")
        ch_outer.addWidget(self._channel_detail_title)
        ch_form = QFormLayout()
        self.detail_platform_edit = QLineEdit()
        self.detail_platform_edit.setPlaceholderText("プラットフォーム名（任意・仕入チャネルから補完可）")
        ch_form.addRow("プラットフォーム:", self.detail_platform_edit)
        self.detail_transaction_id_edit = QLineEdit()
        self.detail_transaction_id_edit.setPlaceholderText("取引ID（任意）")
        ch_form.addRow("取引ID:", self.detail_transaction_id_edit)
        self.detail_seller_username_edit = QLineEdit()
        self.detail_seller_username_edit.setPlaceholderText("ユーザー名・出品者名（任意）")
        ch_form.addRow("ユーザー名:", self.detail_seller_username_edit)
        self.detail_listing_url_edit = QLineEdit()
        self.detail_listing_url_edit.setPlaceholderText("出品ページURL（任意）")
        ch_form.addRow("出品URL:", self.detail_listing_url_edit)
        self.detail_tracking_edit = QLineEdit()
        self.detail_tracking_edit.setPlaceholderText("伝票番号・追跡番号（任意）")
        ch_form.addRow("伝票番号:", self.detail_tracking_edit)
        self.detail_prefecture_edit = QLineEdit()
        self.detail_prefecture_edit.setPlaceholderText("受取都道府県（任意）")
        ch_form.addRow("受取都道府県:", self.detail_prefecture_edit)
        ch_outer.addLayout(ch_form)

        self.register_flea_user_master_btn = QPushButton("フリマユーザーをマスタ登録")
        self.register_flea_user_master_btn.setToolTip(
            "右側に入力したプラットフォーム・ユーザー名などを、"
            "「データベース管理 > 店舗マスタ > フリマユーザー一覧」に登録します。"
        )
        self.register_flea_user_master_btn.clicked.connect(self._on_register_flea_market_user_master)
        self.register_flea_user_master_btn.setVisible(False)
        ch_outer.addWidget(self.register_flea_user_master_btn)

        ch_outer.addStretch()
        self._splitter.addWidget(self._channel_detail_widget)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([620, 400])

        main_layout.addWidget(self._splitter)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        main_layout.addWidget(bb)
        self._sync_missing_custom_checkboxes_enabled()
        self.source_type_combo.currentTextChanged.connect(self._on_source_type_changed)
        self.source_channel_combo.currentTextChanged.connect(self._on_detail_channel_text_for_platform)
        self._on_source_type_changed(self.source_type_combo.currentText())

    def accept(self):
        if not self.asin_edit.text().strip():
            QMessageBox.warning(self, "入力エラー", "ASINは必須です。")
            return
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "入力エラー", "商品名は必須です。")
            return
        super().accept()

    def _apply_custom_missing_checkbox_labels(self) -> None:
        """詳細説明タブで保存したカスタム名称をチェックボックス表示に反映"""
        try:
            md = self.condition_template_db.load_missing_keywords()
            lab = md.get("custom_labels") or {}
            defaults = {"custom1": "カスタム1", "custom2": "カスタム2", "custom3": "カスタム3"}
            self.missing_custom1_checkbox.setText(lab.get("custom1") or defaults["custom1"])
            self.missing_custom2_checkbox.setText(lab.get("custom2") or defaults["custom2"])
            self.missing_custom3_checkbox.setText(lab.get("custom3") or defaults["custom3"])
        except Exception:
            pass

    def _sync_missing_custom_checkboxes_enabled(self) -> None:
        """取説欠品・内箱欠品のどちらかがONのときはカスタムを選べない"""
        fixed_on = self.missing_manual_checkbox.isChecked() or self.missing_inner_box_checkbox.isChecked()
        custom_cbs = (
            self.missing_custom1_checkbox,
            self.missing_custom2_checkbox,
            self.missing_custom3_checkbox,
        )
        for cb in custom_cbs:
            if fixed_on:
                cb.setChecked(False)
            cb.setEnabled(not fixed_on)
            cb.setToolTip(
                "取説欠品・内箱欠品のチェックを外すと、こちらを選べます。"
                if fixed_on
                else ""
            )

    def _on_call_condition_note(self):
        condition_text = self.condition_combo.currentText().strip()
        if not condition_text:
            QMessageBox.information(self, "呼び出し", "先に「コンディション」を選択してください。")
            return
        try:
            condition_key = self.get_condition_key(condition_text)
            text = self.condition_template_db.get_condition_description_text(condition_key)
            if not text:
                QMessageBox.information(
                    self,
                    "呼び出し",
                    f"コンディション「{condition_text}」に対応する説明が登録されていません。\nコンディション説明タブで登録してください。"
                )
                return
            text = _normalize_condition_note_newlines(text)

            # 欠品・詳細（カスタム）チェックに応じて「詳細説明」タブの文面を挿入
            manual_checked = bool(self.missing_manual_checkbox.isChecked())
            inner_box_checked = bool(self.missing_inner_box_checkbox.isChecked())
            missing_key = ""
            if manual_checked and inner_box_checked:
                missing_key = "取説・内箱欠品"
            elif manual_checked:
                missing_key = "取説欠品"
            elif inner_box_checked:
                missing_key = "内箱欠品"

            missing_data = self.condition_template_db.load_missing_keywords()
            kw = missing_data.get("keywords", {}) or {}

            if missing_key:
                missing_text = str(kw.get(missing_key, "") or "").strip()
                if missing_text:
                    if "{欠品}" in text:
                        text = text.replace("{欠品}", missing_text)
                    elif "【付属品】" in text:
                        text = text.replace("【付属品】", f"【付属品】{missing_text}")
                    else:
                        text = f"{text}\n【付属品】{missing_text}".strip()

            extra_parts: List[str] = []
            for ck, cb in (
                ("custom1", self.missing_custom1_checkbox),
                ("custom2", self.missing_custom2_checkbox),
                ("custom3", self.missing_custom3_checkbox),
            ):
                if cb.isChecked():
                    part = str(kw.get(ck, "") or "").strip()
                    if part:
                        extra_parts.append(part)
            if extra_parts:
                extra_block = "\n".join(extra_parts)
                text = f"{text.rstrip()}\n{extra_block}".strip() if text.strip() else extra_block

            self.condition_note_edit.setPlainText(text)
        except Exception as e:
            QMessageBox.warning(self, "呼び出しエラー", f"コンディション説明の呼び出しに失敗しました。\n{str(e)}")

    def _on_source_type_changed(self, source_type: str):
        source_type = (source_type or "").strip()
        self.source_supplier_combo.blockSignals(True)
        self.source_supplier_combo.clear()
        self.source_channel_combo.blockSignals(True)
        self.source_channel_combo.clear()

        if source_type == "実店舗":
            self.source_channel_combo.addItem("実店舗")
            self.source_channel_combo.setCurrentText("実店舗")
            for s in self.store_db.list_stores():
                code = (s.get("store_code") or s.get("supplier_code") or "").strip()
                name = (s.get("store_name") or "").strip()
                if code and name:
                    self.source_supplier_combo.addItem(f"{code} - {name}", {"code": code, "name": name})
        elif source_type == "電脳":
            platforms = self.store_db.list_online_platforms(active_only=True)
            for p in platforms:
                self.source_channel_combo.addItem(p.get("platform_name") or "")
            if self.source_channel_combo.count() == 0:
                self.source_channel_combo.addItems(self.SOURCE_CHANNEL_PRESETS)
            self._reload_online_suppliers_for_channel(self.source_channel_combo.currentText().strip())
        elif source_type == "フリマ":
            markets = self.store_db.list_flea_markets(active_only=True)
            for m in markets:
                self.source_channel_combo.addItem(m.get("platform_name") or "")
            if self.source_channel_combo.count() == 0:
                self.source_channel_combo.addItems(self.SOURCE_CHANNEL_PRESETS)
            self._reload_flea_suppliers_for_channel(self.source_channel_combo.currentText().strip())
        else:
            # 想定外の仕入種別（旧バージョンの「問屋」など）のときは実店舗と同じ構成にする
            self.source_channel_combo.addItem("実店舗")
            self.source_channel_combo.setCurrentText("実店舗")
            for s in self.store_db.list_stores():
                code = (s.get("store_code") or s.get("supplier_code") or "").strip()
                name = (s.get("store_name") or "").strip()
                if code and name:
                    self.source_supplier_combo.addItem(f"{code} - {name}", {"code": code, "name": name})

        self.source_channel_combo.blockSignals(False)
        self.source_supplier_combo.blockSignals(False)
        self._on_source_supplier_changed()
        self._sync_channel_detail_panel()

    def _on_detail_channel_text_for_platform(self, text: str):
        """仕入チャネル変更時、右ペインのプラットフォームが空なら同じ文字列で補完。"""
        if not self._channel_detail_widget.isVisible():
            return
        if self.detail_platform_edit.text().strip():
            return
        self.detail_platform_edit.setText((text or "").strip())

    def _clear_channel_detail_fields(self) -> None:
        for w in (
            self.detail_platform_edit,
            self.detail_transaction_id_edit,
            self.detail_seller_username_edit,
            self.detail_listing_url_edit,
            self.detail_tracking_edit,
            self.detail_prefecture_edit,
        ):
            w.clear()

    def _sync_channel_detail_panel(self) -> None:
        st = (self.source_type_combo.currentText() or "").strip()
        show = st in ("フリマ", "電脳")
        self._channel_detail_widget.setVisible(show)
        if hasattr(self, "register_flea_user_master_btn"):
            self.register_flea_user_master_btn.setVisible(st == "フリマ")
        if show:
            self.setMinimumWidth(960)
            self._channel_detail_title.setText(
                "フリマ取引情報" if st == "フリマ" else "電脳取引情報"
            )
            if not self.detail_platform_edit.text().strip():
                self.detail_platform_edit.setText(
                    (self.source_channel_combo.currentText() or "").strip()
                )
        else:
            self.setMinimumWidth(520)
            self._clear_channel_detail_fields()

    def _resolve_flea_market_from_single_purchase_form(self) -> Optional[Dict[str, Any]]:
        """仕入チャネル／プラットフォーム欄から flea_markets の1行を特定する。"""
        name = (self.detail_platform_edit.text() or "").strip() or (
            self.source_channel_combo.currentText() or ""
        ).strip()
        if not name:
            return None
        markets = self.store_db.list_flea_markets(active_only=False)
        for m in markets:
            if (m.get("platform_name") or "").strip() == name:
                return m
        nl = name.lower()
        for m in markets:
            pn = (m.get("platform_name") or "").strip()
            if pn.lower() == nl:
                return m
        return None

    def _on_register_flea_market_user_master(self) -> None:
        """単品仕入入力中のフリマ取引情報から、フリマユーザー一覧マスタへ登録する。"""
        if (self.source_type_combo.currentText() or "").strip() != "フリマ":
            QMessageBox.information(
                self,
                "マスタ登録",
                "仕入種別が「フリマ」のときだけ利用できます。",
            )
            return
        market = self._resolve_flea_market_from_single_purchase_form()
        if not market:
            QMessageBox.warning(
                self,
                "マスタ登録",
                "フリマプラットフォームを特定できませんでした。\n"
                "「設定 > 店舗コード設定 > フリマコード」に名称が一致する行があるか確認してください。",
            )
            return
        code = (market.get("platform_code") or "").strip().upper()
        pname = (market.get("platform_name") or "").strip()
        username = (self.detail_seller_username_edit.text() or "").strip()
        listing = (self.detail_listing_url_edit.text() or "").strip()
        tx_id = (self.detail_transaction_id_edit.text() or "").strip()
        unique_id = listing or tx_id

        try:
            from ui.store_master_widget import FleaMarketUserEditDialog
        except Exception as e:
            QMessageBox.warning(self, "マスタ登録", f"登録画面の読み込みに失敗しました:\n{e}")
            return

        existing = self.store_db.find_flea_market_user(
            code, username=username or None, unique_id=unique_id or None
        )
        if existing:
            r = QMessageBox.question(
                self,
                "マスタ登録",
                "同じプラットフォームで、ユーザー名または固有IDが一致する登録が既にあります。\n"
                "編集画面を開きますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if r != QMessageBox.Yes:
                return
            dlg = FleaMarketUserEditDialog(self, data=existing)
        else:
            prefill: Dict[str, Any] = {
                "platform_code": code,
                "platform_name": pname,
                "username": username,
                "unique_id": unique_id,
                "rating_tier": "",
                "identity_verified": 0,
                "notes": "",
            }
            dlg = FleaMarketUserEditDialog(self, data=prefill)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        try:
            if existing:
                self.store_db.update_flea_market_user(int(existing["id"]), data)
                QMessageBox.information(self, "マスタ登録", "フリマユーザーマスタを更新しました。")
            else:
                self.store_db.add_flea_market_user(data)
                QMessageBox.information(self, "マスタ登録", "フリマユーザーマスタに登録しました。")
        except Exception as e:
            QMessageBox.warning(self, "マスタ登録", f"保存に失敗しました:\n{e}")

    def _on_source_channel_changed(self, channel: str):
        source_type = (self.source_type_combo.currentText() or "").strip()
        ch = (channel or "").strip()
        if source_type == "電脳":
            self._reload_online_suppliers_for_channel(ch)
            self._on_source_supplier_changed()
        elif source_type == "フリマ":
            self._reload_flea_suppliers_for_channel(ch)
            self._on_source_supplier_changed()

    def _reload_online_suppliers_for_channel(self, channel_name: str):
        self.source_supplier_combo.blockSignals(True)
        self.source_supplier_combo.clear()
        rows = self.store_db.list_online_stores(active_only=True)
        for r in rows:
            p_name = (r.get("platform_name") or "").strip()
            if channel_name and p_name != channel_name:
                continue
            code = (r.get("supplier_code") or "").strip()
            shop = (r.get("shop_name") or "").strip()
            if code and shop:
                self.source_supplier_combo.addItem(f"{code} - {shop}", {"code": code, "name": shop})
        self.source_supplier_combo.blockSignals(False)

    def _reload_flea_suppliers_for_channel(self, channel_name: str):
        """設定 > DB設定 > フリマ の有効マスタから、チャネル（プラットフォーム名）に合う候補を列挙"""
        self.source_supplier_combo.blockSignals(True)
        self.source_supplier_combo.clear()
        for m in self.store_db.list_flea_markets(active_only=True):
            p_name = (m.get("platform_name") or "").strip()
            if channel_name and p_name != channel_name:
                continue
            code = (m.get("platform_code") or "").strip()
            if code and p_name:
                self.source_supplier_combo.addItem(f"{code} - {p_name}", {"code": code, "name": p_name})
        self.source_supplier_combo.blockSignals(False)

    def _on_source_supplier_changed(self):
        data = self.source_supplier_combo.currentData()
        if isinstance(data, dict):
            self.store_code_edit.setText((data.get("code") or "").strip())
        elif self.source_type_combo.currentText().strip() == "実店舗":
            # 実店舗は候補未選択の場合、誤登録防止のため空にする
            self.store_code_edit.clear()

    def _extract_jan_from_raw_keepa_product(self, raw_product: Dict[str, Any]) -> str:
        """Keepa生データからJAN(13桁)候補を抽出"""
        candidates: List[str] = []
        for key in ("eanList", "ean", "upcList", "upc"):
            value = raw_product.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                for v in value:
                    s = str(v).strip()
                    if s:
                        candidates.append(s)
            else:
                txt = str(value).strip()
                if not txt:
                    continue
                if "," in txt:
                    candidates.extend([t.strip() for t in txt.split(",") if t.strip()])
                else:
                    candidates.append(txt)
        for code in candidates:
            digits = re.sub(r"\D", "", code)
            if len(digits) == 13:
                return digits
        return ""

    def _fill_from_keepa(self, show_success_message: bool = False):
        asin = (self.asin_edit.text() or "").strip().upper()
        self.asin_edit.setText(asin)
        if not asin:
            return
        if len(asin) != 10:
            return
        try:
            info, raw = self.keepa_service.fetch_product_with_raw(asin)
        except Exception as e:
            # 自動補完時はうるさくしない。手動補完時のみ通知。
            if show_success_message:
                QMessageBox.warning(self, "Keepa補完", f"Keepaからの取得に失敗しました。\n{str(e)}")
            return

        jan = self._extract_jan_from_raw_keepa_product(raw)
        if jan:
            self.jan_edit.setText(jan)
        if info.title:
            self.title_edit.setText(str(info.title).strip())

        if show_success_message:
            added = []
            if jan:
                added.append("JAN")
            if info.title:
                added.append("商品名")
            if added:
                QMessageBox.information(self, "Keepa補完", f"{'・'.join(added)}を補完しました。")
            else:
                QMessageBox.information(self, "Keepa補完", "補完可能なJAN/商品名が見つかりませんでした。")

    def _on_asin_editing_finished(self):
        self._fill_from_keepa(show_success_message=False)

    def _fill_from_keepa_button_clicked(self):
        self._fill_from_keepa(show_success_message=True)

    def _open_fba_simulator_url(self):
        settings = QSettings("HIRIO", "DesktopApp")
        default_url = "https://sellercentral.amazon.co.jp/revcalpublic?lang=ja_JP"
        url = str(settings.value("amazon/fba_simulator_url", default_url) or default_url).strip()
        if not url:
            url = default_url
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            QMessageBox.warning(self, "URL確認", "FBA料金シミュレーターURLが不正です。設定タブで確認してください。")
            return
        QDesktopServices.openUrl(QUrl(url))

    @staticmethod
    def _extract_yen_amount_from_text(text: str, labels: List[str]) -> Optional[int]:
        if not text:
            return None
        normalized = text.replace("\u00a5", "¥")
        patterns: List[re.Pattern] = []
        for label in labels:
            escaped = re.escape(label)
            # 金額は半角・全角数字の両方（OCR揺れ対応）
            patterns.append(
                re.compile(
                    rf"{escaped}[^\n\r\d¥￥０-９\-−]*[-−]?\s*[¥￥]?\s*([0-9０-９][0-9０-９,，]*)",
                    re.IGNORECASE,
                )
            )
        for pat in patterns:
            m = pat.search(normalized)
            if m:
                n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                if n is not None:
                    return n
        return None

    @staticmethod
    def _extract_yen_amount_by_keywords(
        text: str,
        must_include_keywords: List[str],
    ) -> Optional[int]:
        """
        行単位で、指定キーワードをすべて含む行から金額を抽出する。
        OCR揺れ（空白・全角/半角）に強くするため、比較時は空白除去して小文字化する。
        """
        if not text:
            return None
        lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
        normalized_keywords = [k.lower().replace(" ", "") for k in must_include_keywords if k]
        for line in lines:
            norm_line = line.lower().replace(" ", "")
            if not all(k in norm_line for k in normalized_keywords):
                continue
            m = re.search(r"[-−]?\s*[¥￥]?\s*([0-9０-９][0-9０-９,，]*)", line)
            if not m:
                continue
            n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
            if n is not None:
                return n
        return None

    @staticmethod
    def _parse_yen_int_token(token: str) -> Optional[int]:
        """OCRの金額トークン（全角数字・カンマ混在可）を int に変換"""
        if not token:
            return None
        s = token.translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
        raw = re.sub(r"[^\d]", "", s)
        if not raw:
            return None
        try:
            n = int(raw)
            return n if n > 0 else None
        except ValueError:
            return None

    # 料金シミュの「¥のみの行」でよく出るが商品価格ではない金額（先頭候補から除外）
    _PLANNED_PRICE_STANDALONE_BLACKLIST = frozenset({9, 100, 425, 534, 757, 857})

    @staticmethod
    def _extract_planned_price_from_standalone_amount_lines(text: str) -> Optional[int]:
        """
        Tesseract 等でラベルが文字化けし、金額だけが「¥ 7,280」のように1行に出るケース向け。
        行全体が（短い記号＋金額）程度のときだけ採用し、よくある手数料額はスキップする。
        """
        if not text:
            return None
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            s = line.strip()
            if not s or "%" in s:
                continue
            m = re.fullmatch(r"[^0-9０-９]{0,8}([0-9０-９][0-9０-９,，]*)\s*", s)
            if not m:
                continue
            n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
            if n is None or n < 500:
                continue
            if n in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                continue
            return n
        return None

    @staticmethod
    def _extract_planned_selling_price_yen(text: str) -> Optional[int]:
        """
        「商品価格」等から販売予定価格候補を抽出。
        OCRでラベルと金額が別行になっても拾えるよう、空白除去全文マッチと近傍行走査を行う。
        """
        if not text:
            return None
        t = text.replace("\u00a5", "¥")
        # 日本語ラベルは「改行なし1本化」で拾わない（売上の合計→次行Amazon手数料¥857が
        # 1続きになり、857 等を誤認するため）。英字ラベルのみ ws_free で試す。
        labels_compact_en = [
            r"product\s*price",
            r"item\s*price",
            r"listing\s*price",
        ]
        ws_free = re.sub(r"[\s\r\n　\t]+", "", t, flags=re.UNICODE)
        for pat in labels_compact_en:
            m = re.search(
                rf"(?:{pat})[:：\-−￥¥]*([0-9０-９][0-9０-９,，]*)",
                ws_free,
                flags=re.IGNORECASE,
            )
            if m:
                n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                if n is not None and n not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                    return n

        # 従来どおり（同一行にラベル+金額がある場合）
        # ※「売上」+「合計」キーワード検索は「売上の見積り」等と誤マッチするため使わない
        for attempt in (
            lambda: SinglePurchaseInputDialog._extract_yen_amount_from_text(
                t,
                [
                    "商品価格",
                    "売上の合計",
                    "売上合計",
                    "product price",
                    "Product Price",
                    "Item price",
                    "Listing price",
                ],
            ),
            lambda: SinglePurchaseInputDialog._extract_yen_amount_by_keywords(t, ["商品価格"]),
        ):
            v = attempt()
            if v is not None and v not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                return v

        # 「商品」「価格」が隣接行に分かれたOCR（出品者出荷で多い）
        lines = [ln.rstrip() for ln in t.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        nonempty_idx = [i for i, ln in enumerate(lines) if ln.strip()]
        for k in range(len(nonempty_idx)):
            seg = "".join(lines[j].strip() for j in nonempty_idx[k : min(k + 3, len(nonempty_idx))])
            seg_nospace = re.sub(r"[\s　]+", "", seg)
            if "商品価格" in seg_nospace or ("商品" in seg_nospace and "価格" in seg_nospace and "手数料" not in seg_nospace):
                m = re.search(r"[-−￥¥:：]?\s*([0-9０-９][0-9０-９,，]*)", seg)
                if m:
                    n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                    if n is not None and n not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                        return n

        # ラベルが文字化けしても「価格」だけ残る行＋その後に金額ブロックが離れて出るケース（出品者出荷）
        for i, line in enumerate(lines):
            if "価格" not in line:
                continue
            if any(x in line for x in ("手数料", "成約料", "保管", "月額", "あたり")):
                continue
            if "配送料" in line or line.strip() in ("送料",):
                continue
            m = re.search(r"[-−]?\s*[¥￥]?\s*([0-9０-９][0-9０-９,，]*)", line)
            if m:
                n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                if n is not None and n not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                    return n
            for j in range(i + 1, min(i + 45, len(lines))):
                fl = lines[j].strip()
                if not fl:
                    continue
                if "配送料" in fl or fl in ("送料",):
                    continue
                if "その他の費用" in fl or "割引" in fl or "プロモーション" in fl:
                    continue
                if any(k in fl for k in ("手数料", "出荷費用", "在庫保管", "成約料", "純利益", "利益率", "見積り", "見積")):
                    continue
                if "費用" in fl and "商品あたり" in fl.replace(" ", "").replace("　", ""):
                    continue
                m = re.search(r"[-−]?\s*[¥￥]?\s*([0-9０-９][0-9０-９,，]*)", fl)
                if m:
                    n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                    if n is not None and n not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                        return n

        # ラベル行の直後数行から金額を探す（FBAシミュ等で縦並びのとき）
        _skip_substrings = (
            "配送料",
            "送料",
            "shipping",
            "手数料",
            "出荷費用",
            "出荷作業",
            "配送代行",
            "在庫保管",
            "成約料",
            "純利益",
            "利益率",
            "見積",
            "あたりの費用",
            "費用",
        )

        def _line_skipped_for_price_follow(fl: str) -> bool:
            s = fl.strip()
            if not s:
                return True
            # 出品者出荷で商品価格の直後に来る「配送料」はスキップ（次の「売上の合計」等を拾う）
            if "配送料" in s or "送料" in s:
                return True
            skip_tokens = [x for x in _skip_substrings if x != "費用"]
            if any(x in s for x in skip_tokens):
                return True
            if "費用" in s and "商品あたり" in s.replace(" ", "").replace("　", ""):
                return True
            return False

        for i, line in enumerate(lines):
            low = line.lower().replace(" ", "").replace("　", "")
            is_product_price_row = (
                "商品価格" in low
                or "productprice" in low
                or ("itemprice" in low)
                or ("listingprice" in low)
            )
            if not is_product_price_row:
                if "商品" in low and "価格" in low and "手数料" not in low and "あたり" not in low:
                    is_product_price_row = True
            if not is_product_price_row:
                continue
            if any(x in line for x in ("あたり", "保管", "成約料", "純利益", "利益率")):
                continue
            m = re.search(r"[-−]?\s*[¥￥]?\s*([0-9０-９][0-9０-９,，]*)", line)
            if m:
                n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                if n is not None and n not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                    return n
            for j in range(i + 1, min(i + 30, len(lines))):
                fl = lines[j].strip()
                if _line_skipped_for_price_follow(fl):
                    continue
                if "その他の費用" in fl:
                    continue
                m = re.search(r"[-−]?\s*[¥￥]?\s*([0-9０-９][0-9０-９,，]*)", fl)
                if m:
                    n = SinglePurchaseInputDialog._parse_yen_int_token(m.group(1) or "")
                    if n is not None and n not in SinglePurchaseInputDialog._PLANNED_PRICE_STANDALONE_BLACKLIST:
                        return n

        # 最後の手段: 行がほぼ「記号+金額」だけ（ラベル文字化けで金額列だけ読めた場合）
        return SinglePurchaseInputDialog._extract_planned_price_from_standalone_amount_lines(t)

    @staticmethod
    def _detect_shipping_method_from_fee_simulator_ocr(text: str) -> Optional[str]:
        """
        Amazon料金シミュレーター等の先頭見出しから発送方法を推定。
        - 「Amazonから出荷」→ FBA
        - 「出品者出荷」→ 自己発送
        先頭付近のみ見て、本文中の「Amazon」誤検出を減らす。
        """
        if not text:
            return None
        nonempty = [ln.strip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
        head_joined = "".join(re.sub(r"[\s　]+", "", ln) for ln in nonempty[:14])
        low = head_joined.lower()

        idx_seller = head_joined.find("出品者出荷")
        idx_amazon_ship = head_joined.find("Amazonから出荷")
        if idx_amazon_ship < 0:
            idx_amazon_ship = low.find("amazonから出荷")

        if idx_seller >= 0 and (idx_amazon_ship < 0 or idx_seller < idx_amazon_ship):
            return "自己発送"
        if idx_amazon_ship >= 0:
            return "FBA"
        return None

    def _load_fees_from_image_ocr(self):
        temp_image_path: Optional[str] = None
        image_path = ""
        source_name = "クリップボード"
        clipboard = QApplication.clipboard()
        clip_image = clipboard.image()
        if clip_image and not clip_image.isNull():
            fd, temp_image_path = tempfile.mkstemp(prefix="hirio_fee_ocr_", suffix=".png")
            os.close(fd)
            if not clip_image.save(temp_image_path, "PNG"):
                try:
                    os.unlink(temp_image_path)
                except Exception:
                    pass
                QMessageBox.warning(self, "OCR", "クリップボード画像の保存に失敗しました。")
                return
            image_path = temp_image_path
        else:
            fallback = QMessageBox.question(
                self,
                "OCR",
                "クリップボードに画像がありません。\nファイルを選択して読み込みますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if fallback != QMessageBox.Yes:
                return
            source_name = "ファイル"
            image_path, _ = QFileDialog.getOpenFileName(
                self,
                "FBA料金シミュレーター画像を選択",
                "",
                "画像ファイル (*.png *.jpg *.jpeg *.webp *.bmp)"
            )
            if not image_path:
                return
        try:
            result = self.ocr_service.extract_text(image_path, use_preprocessing=True)
            text = str(result.get("text") or "")
            if not text.strip():
                QMessageBox.warning(self, "OCR", "文字を読み取れませんでした。別の画像でお試しください。")
                return

            # FBAシミュ先頭見出し → 発送方法
            shipping_method = self._detect_shipping_method_from_fee_simulator_ocr(text)

            # FBAシミュ・出品画面などの「商品価格」→ 販売予定価格（別行OCRにも対応）
            planned_from_ocr = self._extract_planned_selling_price_yen(text)

            amazon_fee = self._extract_yen_amount_from_text(
                text,
                ["Amazon手数料", "amazon手数料", "販売手数料", "referral fee"]
            )
            if amazon_fee is None:
                # 「Amazon 手数料」のようなOCR揺れに対応
                amazon_fee = self._extract_yen_amount_by_keywords(text, ["amazon", "手数料"])
            if amazon_fee is None:
                # 明細行しか拾えないケースは、販売手数料 + 基本成約料 + カテゴリー別成約料 を合算
                referral_fee = self._extract_yen_amount_from_text(text, ["販売手数料", "referral fee"])
                closing_fee = self._extract_yen_amount_from_text(text, ["基本成約料"])
                category_fee = self._extract_yen_amount_from_text(text, ["カテゴリー別成約料"])
                if referral_fee is not None:
                    amazon_fee = referral_fee + (closing_fee or 0) + (category_fee or 0)
            shipping_cost = self._extract_yen_amount_from_text(
                text,
                ["出荷費用", "出荷作業手数料", "配送代行手数料", "fulfillment fee"]
            )
            storage_fee = self._extract_yen_amount_from_text(
                text,
                ["在庫保管手数料", "月間在庫保管手数料", "storage fee"]
            )

            updated_items: List[str] = []
            if shipping_method:
                idx = self.shipping_combo.findText(shipping_method)
                if idx >= 0:
                    self.shipping_combo.setCurrentIndex(idx)
                    updated_items.append("発送方法")
            if planned_from_ocr is not None:
                self.planned_price_spin.setValue(planned_from_ocr)
                updated_items.append("販売予定価格")
            if amazon_fee is not None:
                self.amazon_fee_spin.setValue(amazon_fee)
                updated_items.append(COL_PLATFORM_FEE)
            if shipping_cost is not None:
                self.shipping_cost_spin.setValue(shipping_cost)
                updated_items.append("出荷費用")
            if storage_fee is not None:
                self.storage_fee_spin.setValue(storage_fee)
                updated_items.append("在庫保管手数料")

            if not updated_items:
                QMessageBox.information(
                    self,
                    "OCR",
                    "見出し・商品価格・手数料の候補を見つけられませんでした。画像を拡大して再撮影するか、手入力してください。"
                )
                return
            QMessageBox.information(
                self,
                "OCR",
                f"{source_name}OCRで {', '.join(updated_items)} を入力しました。数値を確認して保存してください。"
            )
        except Exception as e:
            QMessageBox.warning(self, "OCRエラー", f"画像読取に失敗しました。\n{str(e)}")
        finally:
            if temp_image_path:
                try:
                    os.unlink(temp_image_path)
                except Exception:
                    pass

    def _on_generate_sku_clicked(self):
        """仕入データタブの generate_sku と同系統（1件分・API・店舗/電脳/フリママスタ・SKU日付・末尾M）。"""
        inv = self._inventory_widget
        if inv is None or not getattr(inv, "api_client", None):
            QMessageBox.warning(self, "SKU生成", "仕入管理から開いていないため、SKUを生成できません。")
            return

        preview = self.get_row_data()
        if inv._is_excluded_for_sku(preview):
            QMessageBox.warning(
                self,
                "SKU生成",
                "この内容はSKU生成の対象外です（コメントに「除外」が含まれる、または発送方法が空です）。",
            )
            return
        if not (preview.get("ASIN") or "").strip() or not (preview.get("商品名") or "").strip():
            QMessageBox.warning(self, "SKU生成", "ASINと商品名を入力してください。")
            return

        purchase_date = str(preview.get("仕入れ日", "") or "").strip()
        asin = str(preview.get("ASIN", "") or "").strip()
        existing = inv.lookup_existing_sku_for_date_asin(purchase_date, asin)
        if existing:
            self.sku_edit.setText(existing)
            QMessageBox.information(
                self,
                "SKU生成",
                f"商品DBに一致するSKUがありました。\n{existing}",
            )
            return

        enriched = dict(preview)
        for col in inv.column_headers:
            if col not in enriched:
                enriched[col] = ""

        supplier_code = str(preview.get("仕入先", "") or "").strip()
        if supplier_code and inv:
            inv._ensure_missing_stores_registered(
                [(supplier_code, supplier_code)],
                show_message=False,
            )

        store_not_found: List[str] = []
        if supplier_code:
            resolved = self.store_db.resolve_supplier_for_sku(supplier_code)
            if resolved:
                enriched["supplier_code"] = resolved["supplier_code"]
                enriched["store_name"] = resolved.get("store_name", "")
                enriched["store_id"] = resolved.get("store_id")
            else:
                store_not_found.append(supplier_code)
                enriched["supplier_code"] = supplier_code
                enriched["store_name"] = ""
                enriched["store_id"] = None
        else:
            enriched["supplier_code"] = ""
            enriched["store_name"] = ""
            enriched["store_id"] = None

        if store_not_found:
            QMessageBox.warning(
                self,
                "店舗情報警告",
                f"仕入先コードに対応する店舗が見つかりませんでした:\n{', '.join(store_not_found)}",
            )

        sku_date_str = None
        if hasattr(inv, "sku_date_edit") and inv.sku_date_edit is not None:
            d = inv.sku_date_edit.date()
            if d.isValid():
                sku_date_str = d.toString("yyyyMMdd")

        try:
            result = inv.api_client.inventory_generate_sku([enriched], sku_date=sku_date_str)
        except Exception as e:
            QMessageBox.critical(self, "SKU生成エラー", f"SKU生成中にエラーが発生しました:\n{str(e)}")
            return

        if result.get("status") != "success" or not result.get("results"):
            QMessageBox.warning(self, "SKU生成失敗", "SKU生成に失敗しました。")
            return

        sku_res = result["results"][0]
        if sku_res.get("status") != "success":
            QMessageBox.warning(self, "SKU生成失敗", "SKU生成に失敗しました。")
            return

        generated_sku = sku_res.get("generated_sku") or ""
        if hasattr(inv, "chk_append_m_for_self_ship") and inv.chk_append_m_for_self_ship.isChecked():
            ship_method = str(self.shipping_combo.currentText() or "")
            if "自己発送" in ship_method and isinstance(generated_sku, str) and generated_sku and not generated_sku.endswith("M"):
                generated_sku = f"{generated_sku}M"

        self.sku_edit.setText(generated_sku)
        QMessageBox.information(self, "SKU生成完了", f"SKUを生成しました。\n{generated_sku}")

        try:
            inv.sku_generated.emit(1)
        except Exception:
            pass

        if hasattr(inv, "sku_date_edit") and inv.sku_date_edit is not None:
            inv.sku_date_edit.setDate(QDate.currentDate())

    def get_row_data(self) -> Dict[str, Any]:
        purchase_price = int(self.purchase_price_spin.value())
        planned_price = int(self.planned_price_spin.value())
        amazon_fee = int(self.amazon_fee_spin.value())
        shipping_cost = int(self.shipping_cost_spin.value())
        storage_fee = int(self.storage_fee_spin.value())
        # 仕入一覧と同式: 損益分岐点 = 仕入+手数料+出荷、見込み利益 = 販売予定-損益分岐点（保管手数料は含めない）
        break_even_sum = purchase_price + amazon_fee + shipping_cost
        total_cost = amazon_fee + shipping_cost
        expected_profit = planned_price - break_even_sum
        expected_margin = round((expected_profit / planned_price) * 100, 2) if planned_price > 0 else 0.0
        expected_roi = round((expected_profit / purchase_price) * 100, 2) if purchase_price > 0 else 0.0

        source_type = self.source_type_combo.currentText().strip()
        source_channel = self.source_channel_combo.currentText().strip() or "未設定"
        order_id = self.order_id_edit.text().strip()
        store_code = self.store_code_edit.text().strip()
        if not store_code:
            store_code = f"{source_type}:{source_channel}"

        header_comment = f"[単品仕入][{source_type}:{source_channel}]"
        if order_id:
            header_comment += f"[注文:{order_id}]"
        body_comment = self.comment_edit.toPlainText().strip()
        merged_comment = f"{header_comment} {body_comment}".strip()

        condition_note = _to_stored_newlines(self.condition_note_edit.toPlainText().strip())

        sku_text = self.sku_edit.text().strip()
        if not sku_text:
            sku_text = "未実装"

        if source_type in ("フリマ", "電脳"):
            platform_val = self.detail_platform_edit.text().strip() or source_channel
            tx_id = self.detail_transaction_id_edit.text().strip()
            seller_name = self.detail_seller_username_edit.text().strip()
            listing_url = self.detail_listing_url_edit.text().strip()
            tracking_no = self.detail_tracking_edit.text().strip()
            recv_pref = self.detail_prefecture_edit.text().strip()
        else:
            platform_val = ""
            tx_id = ""
            seller_name = ""
            listing_url = ""
            tracking_no = ""
            recv_pref = ""

        return {
            "仕入れ日": self.purchase_date_edit.date().toString("yyyy-MM-dd"),
            "コンディション": self.condition_combo.currentText().strip() or "中古(良い)",
            "SKU": sku_text,
            "ASIN": self.asin_edit.text().strip(),
            "JAN": self.jan_edit.text().strip(),
            "商品名": self.title_edit.text().strip(),
            "仕入れ個数": int(self.quantity_spin.value()),
            "仕入れ価格": purchase_price,
            "販売予定価格": planned_price,
            "見込み利益": expected_profit,
            "損益分岐点": break_even_sum,
            "想定利益率": expected_margin,
            "想定ROI": expected_roi,
            "コメント": merged_comment,
            "発送方法": self.shipping_combo.currentText().strip() or "FBA",
            "販売チャネル": self.sales_channel_combo.currentText().strip() or "Amazon",
            COL_PLATFORM_FEE: fee_storage_value(amazon_fee),
            COL_SHIPPING: fee_storage_value(shipping_cost),
            COL_TOTAL_COST: fee_storage_value(total_cost),
            "在庫保管手数料": storage_fee,
            "仕入先": store_code,
            "プラットフォーム": platform_val,
            "取引ID": tx_id,
            "ユーザー名": seller_name,
            "出品URL": listing_url,
            "伝票番号": tracking_no,
            "受取都道府県": recv_pref,
            "価格改定": "ON",
            "コンディション説明": condition_note,
        }

