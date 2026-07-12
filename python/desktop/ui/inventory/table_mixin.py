#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在庫一覧・フィルタ・統計 mixin。"""
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
from .row_edit_dialog import InventoryRowEditDialog


class InventoryTableMixin:
    def setup_search_listing_panel(self):
        """検索・フィルタと出品設定をまとめたエリア"""
        self.search_listing_group = QGroupBox("検索・フィルタと出品設定")
        self.search_listing_group.setCheckable(True)
        self.search_listing_group.setChecked(True)
        outer_layout = QVBoxLayout(self.search_listing_group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)
        
        self.search_listing_content = QWidget()
        content_layout = QHBoxLayout(self.search_listing_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        
        # 検索エリア
        search_widget = QWidget()
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)
        search_label = QLabel("検索:")
        search_layout.addWidget(search_label)
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("商品名、ASIN、JANコードで検索...")
        self.search_edit.textChanged.connect(self.apply_filters)
        self.search_edit.setMinimumWidth(220)
        search_layout.addWidget(self.search_edit, 1)
        
        self.clear_search_btn = QPushButton("クリア")
        self.clear_search_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(self.clear_search_btn)
        content_layout.addWidget(search_widget, 2)
        
        # フィルタエリア
        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(6)
        
        price_label = QLabel("販売予定価格:")
        filter_layout.addWidget(price_label)
        
        self.min_price_spin = QSpinBox()
        self.min_price_spin.setRange(0, 999999)
        self.min_price_spin.setValue(0)
        self.min_price_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.min_price_spin.setFixedWidth(70)
        self.min_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.min_price_spin)
        
        price_to_label = QLabel("〜")
        filter_layout.addWidget(price_to_label)
        
        self.max_price_spin = QSpinBox()
        self.max_price_spin.setRange(0, 999999)
        self.max_price_spin.setValue(999999)
        self.max_price_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.max_price_spin.setFixedWidth(70)
        self.max_price_spin.valueChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.max_price_spin)
        
        self.reset_filters_btn = QPushButton("リセット")
        self.reset_filters_btn.clicked.connect(self.reset_filters)
        filter_layout.addWidget(self.reset_filters_btn)
        content_layout.addWidget(filter_widget, 1)
        
        # 出品設定エリア
        listing_settings_widget = self.create_listing_settings_section()
        content_layout.addWidget(listing_settings_widget, 1)
        
        content_layout.addStretch()
        
        outer_layout.addWidget(self.search_listing_content)
        self.search_listing_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        def _on_toggle(checked: bool):
            self.search_listing_content.setVisible(checked)
        self.search_listing_group.toggled.connect(_on_toggle)
        
        self.layout().addWidget(self.search_listing_group)

    def setup_data_table(self):
        """データテーブルエリアの設定（折りたたみ対応）"""
        self.data_group = QGroupBox("仕入データ一覧")
        self.data_group.setCheckable(True)
        self.data_group.setChecked(True)
        outer_layout = QVBoxLayout(self.data_group)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)
        
        self.data_group_content = QWidget()
        data_layout = QVBoxLayout(self.data_group_content)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(6)
        
        # テーブルウィジェットの作成
        self.data_table = QTableWidget()
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.data_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        
        # スクロールバーの設定（常に表示）
        self.data_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.data_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # テーブルのサイズポリシー（高さはExpandingでスクロール可能に）
        self.data_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # 最小高さは設定しない（レイアウトに任せる）
        # 代わりに、親ウィジェットのレイアウトで適切にサイズが決まるようにする
        
        # ヘッダーの設定
        header = self.data_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        
        # 列の定義（17列対応・指定順序）
        # DataFrame上の実際の列名は従来どおり「仕入先」を使用しつつ、
        # 表示ラベルだけ「店舗コード」に差し替える（バックエンドとの互換性維持のため）
        self.column_headers = [
            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "想定利益率", "想定ROI", "コメント",
            "発送方法", "販売チャネル", COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST,
            "在庫保管手数料", "仕入先", "価格改定", "その他詳細", "コンディション説明"
        ]
        # 開発用タブでは、店舗コードの右に「3-6-9」カラムを追加
        if self.dev_mode:
            try:
                base_idx = self.column_headers.index("仕入先") + 1
            except ValueError:
                base_idx = len(self.column_headers)
            extra_columns = ["3-6-9"]
            self.column_headers[base_idx:base_idx] = extra_columns
        try:
            bi = self.column_headers.index("価格改定")
            self.column_headers[bi:bi] = [
                "プラットフォーム",
                "取引ID",
                "ユーザー名",
                "出品URL",
                "伝票番号",
                "受取都道府県",
            ]
        except ValueError:
            pass

        self.data_table.setColumnCount(len(self.column_headers))
        # 表示用のヘッダーラベルを作成（「仕入先」→「店舗コード」に置き換え）
        display_headers = list(self.column_headers)
        try:
            idx = display_headers.index("仕入先")
            display_headers[idx] = "店舗コード"
        except ValueError:
            pass
        self.data_table.setHorizontalHeaderLabels(display_headers)
        # 在庫保管手数料はSP-API運用時に使う想定のため、現段階では一覧では非表示
        if "在庫保管手数料" in self.column_headers:
            self.data_table.setColumnHidden(self.column_headers.index("在庫保管手数料"), True)
        
        # 選択変更時の自動スクロール・ハイライト機能
        self.data_table.itemSelectionChanged.connect(self.on_data_selection_changed)
        # 行のダブルクリックで編集ダイアログを開く
        self.data_table.itemDoubleClicked.connect(self._on_data_row_double_clicked)
        # 仕入れ価格・販売予定価格・手数料・出荷費用の変更で見込み利益等を即時再計算
        self.data_table.itemChanged.connect(self._on_inventory_table_item_changed)
        
        # テーブルをグループに追加（stretch factorを1に設定してスクロール可能に）
        data_layout.addWidget(self.data_table, 1)
        
        # 統計情報をグループ内に配置
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("統計: なし")
        stats_layout.addWidget(self.stats_label)

        # 統計の説明ヘルプ（?ボタン、PRO版 + 開発タブ向け表示）
        self.stats_help_button = QToolButton()
        self.stats_help_button.setText("?")
        self.stats_help_button.setToolTip("仕入健全度や実効利益率の計算方法を表示します。")
        self.stats_help_button.clicked.connect(self._show_stats_help_dialog)
        stats_layout.addWidget(self.stats_help_button)
        # 除外商品確認トグルボタン
        self.toggle_excluded_btn = QPushButton("除外商品確認")
        self.toggle_excluded_btn.setToolTip("コメントに『除外』、または発送方法がFBA以外の商品をハイライト表示します。もう一度押すと解除。")
        self.toggle_excluded_btn.clicked.connect(self.toggle_excluded_highlight)
        stats_layout.addWidget(self.toggle_excluded_btn)
        
        # クリアボタン
        self.data_clear_btn = QPushButton("クリア")
        self.data_clear_btn.clicked.connect(self.clear_inventory_data)
        self.data_clear_btn.setEnabled(False)
        stats_layout.addWidget(self.data_clear_btn)
        
        # 行削除ボタン
        self.data_delete_row_btn = QPushButton("行削除")
        self.data_delete_row_btn.clicked.connect(self.delete_selected_inventory_rows)
        self.data_delete_row_btn.setEnabled(False)
        stats_layout.addWidget(self.data_delete_row_btn)
        
        stats_layout.addStretch()
        data_layout.addLayout(stats_layout)
        
        # コンテンツエリアのサイズポリシー（Expandingでスクロール可能に）
        self.data_group_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer_layout.addWidget(self.data_group_content, 1)  # stretch factorを1に設定
        
        def _on_toggle(checked: bool):
            self.data_group_content.setVisible(checked)
            # スプリッターを使用している場合は、スプリッターが高さを管理する
            # 折りたたみ時は最小高さに、展開時はスプリッターの設定に従う
            if hasattr(self, 'area_splitter'):
                if checked:
                    # 展開時：スプリッターの設定に従う（制限を解除）
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.data_group.setMaximumHeight(16777215)
                else:
                    # 折りたたみ時：最小高さに制限
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.data_group.sizeHint().height()
                    self.data_group.setMaximumHeight(header_height)
                # スプリッターのサイズを再計算
                self.area_splitter.updateGeometry()
            else:
                # スプリッターがない場合の従来の処理（後方互換性のため）
                if checked:
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                    self.data_group.setMaximumHeight(16777215)
                else:
                    self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                    header_height = self.data_group.sizeHint().height()
                    self.data_group.setMaximumHeight(header_height)
            # レイアウトを再計算
            self.data_group.updateGeometry()
            if self.data_group.parent():
                self.data_group.parent().updateGeometry()
        self.data_group.toggled.connect(_on_toggle)
        self.data_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    @staticmethod
    def _row_quantity_multiplier(row) -> float:
        """統計・ルート照合と同様、見込み利益に掛ける仕入れ個数（未入力は1）"""
        for key in ("仕入れ個数", "purchase_count", "quantity", "数量"):
            if key not in row.index and key not in row:
                continue
            try:
                val = row.get(key)
                if val is None or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
                    continue
                q = float(str(val).replace(",", "").strip())
                return max(0.0, q)
            except (ValueError, TypeError):
                continue
        return 1.0

    def update_table(self):
        """テーブルの更新"""
        if self.filtered_data is None:
            return
            
        # テーブルの設定
        row_count = len(self.filtered_data)
        print(f"[DEBUG] update_table: filtered_data行数={row_count}, inventory_data行数={len(self.inventory_data) if self.inventory_data is not None else 0}")
        self.data_table.setRowCount(row_count)
        
        # データの設定（テーブルの行番号は0から始まる連続した番号にする）
        # 価格列の setItem で itemChanged が走ると見込み利益が再計算され CSV 取込値が壊れるためシグナルを止める
        processed_rows = 0
        self.data_table.blockSignals(True)
        try:
            # iterrows()の代わりに、インデックスで直接アクセス
            for table_row_idx in range(row_count):
                if table_row_idx >= len(self.filtered_data):
                    break
                row = self.filtered_data.iloc[table_row_idx]
                for j, column in enumerate(self.column_headers):
                    # Seriesから値を取得（get()ではなく直接アクセス）
                    if column in row.index:
                        value = row[column]
                    else:
                        value = ""
                    value = str(value) if pd.notna(value) else ""
                    if column == "価格改定":
                        value = "OFF" if _is_repricing_enabled_value(value) is False else "ON"
                    elif column == "発送方法" and not str(value).strip():
                        value = "FBA"
                    elif column == "販売チャネル" and not str(value).strip():
                        value = "Amazon"
                    
                    # SKU列の特別処理（空の場合は「未実装」と表示・フル値をUserRoleで保持）
                    if column == "SKU":
                        if not value or value == "" or value == "nan" or pd.isna(value):
                            item = QTableWidgetItem("未実装")
                        else:
                            item = QTableWidgetItem(str(value))
                            item.setData(Qt.UserRole, str(value))  # 保存時にフルSKUを使うため
                    # 商品名列の特別処理（50文字制限+ツールチップ）
                    elif column == "商品名":
                        original_value = value
                        display_value = original_value[:50] + '...' if len(original_value) > 50 else original_value
                        item = QTableWidgetItem(display_value)
                        # 常にフルテキストをツールチップ/UserRoleに保持（保存時はこれを使う）
                        item.setToolTip(original_value)
                        item.setData(Qt.UserRole, original_value)
                    else:
                        item = QTableWidgetItem(value)
                    
                    # 価格列の数値フォーマット
                    if column in [
                        "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点",
                        COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST, "在庫保管手数料",
                    ]:
                        try:
                            zero_empty = is_fee_amount_column(column)
                            if value and str(value).replace(".", "").replace("-", "").replace(",", "").isdigit():
                                num_value = float(str(value).replace(",", ""))
                                item.setText(
                                    format_money_display(num_value, zero_as_empty=zero_empty)
                                )
                            else:
                                item.setText("" if zero_empty else str(value))
                        except Exception:
                            item.setText("" if is_fee_amount_column(column) else str(value))
                    # 利益率とROIの数値フォーマット（小数点第2位まで表示）
                    elif column in ["想定利益率", "想定ROI"]:
                        try:
                            if value and str(value).replace(".", "").replace("-", "").replace(",", "").replace("nan", "").strip():
                                num_value = float(str(value).replace(",", ""))
                                item.setText(f"{num_value:.2f}")
                            else:
                                item.setText("0.00")
                        except:
                            item.setText("0.00")
                    
                    self.data_table.setItem(table_row_idx, j, item)
                processed_rows = max(processed_rows, table_row_idx + 1)
        except Exception as e:
            print(f"[ERROR] update_table: データ設定中にエラー発生: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.data_table.blockSignals(False)
        
        print(f"[DEBUG] update_table: 処理完了。設定した行数={processed_rows}, テーブルの行数={self.data_table.rowCount()}, filtered_data行数={row_count}")
        
        # 行数が一致しない場合は再設定
        if self.data_table.rowCount() != row_count:
            print(f"[WARNING] update_table: テーブルの行数が不一致。再設定します。現在={self.data_table.rowCount()}, 期待値={row_count}")
            self.data_table.setRowCount(row_count)
        
        # 列幅の自動調整
        self.data_table.resizeColumnsToContents()
        
        # 最終確認: テーブルの行数を再度確認
        final_row_count = self.data_table.rowCount()
        if final_row_count != row_count:
            print(f"[ERROR] update_table: 最終確認で行数が不一致。テーブル={final_row_count}, 期待値={row_count}")

        # 除外ハイライトがONなら適用
        if self.excluded_highlight_on:
            self.update_excluded_highlight()
        
        # ボタンの有効/無効を更新
        has_data = self.data_table.rowCount() > 0
        if hasattr(self, 'data_clear_btn'):
            self.data_clear_btn.setEnabled(has_data)

    def _parse_table_int_cell(self, table_row: int, col_name: str) -> int:
        """仕入一覧テーブルのセルを整数（円）として解釈"""
        try:
            j = self.column_headers.index(col_name)
        except ValueError:
            return 0
        item = self.data_table.item(table_row, j)
        if not item:
            return 0
        s = str(item.text()).replace(",", "").strip()
        if not s or s.lower() == "nan":
            return 0
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return 0

    def _write_table_money_cell(self, table_row: int, col_name: str, value: int) -> None:
        j = self.column_headers.index(col_name)
        item = self.data_table.item(table_row, j)
        if not item:
            item = QTableWidgetItem()
            self.data_table.setItem(table_row, j, item)
        item.setText(
            format_money_display(value, zero_as_empty=is_fee_amount_column(col_name))
        )

    def _write_table_rate_cell(self, table_row: int, col_name: str, value: float) -> None:
        j = self.column_headers.index(col_name)
        item = self.data_table.item(table_row, j)
        if not item:
            item = QTableWidgetItem()
            self.data_table.setItem(table_row, j, item)
        item.setText(f"{float(value):.2f}")

    def _recalculate_profit_for_table_row(self, table_row: int) -> None:
        """
        仕入れ価格・販売予定・手数料・出荷・費用合計から
        見込み利益・損益分岐点・想定利益率・想定ROIを再計算してテーブルとDataFrameに反映。
        """
        if self.filtered_data is None or table_row < 0 or table_row >= len(self.filtered_data):
            return
        purchase = self._parse_table_int_cell(table_row, "仕入れ価格")
        planned = self._parse_table_int_cell(table_row, "販売予定価格")
        platform = self._parse_table_int_cell(table_row, COL_PLATFORM_FEE)
        ship = self._parse_table_int_cell(table_row, COL_SHIPPING)
        total = self._parse_table_int_cell(table_row, COL_TOTAL_COST)
        stored_profit = None
        if self.filtered_data is not None and table_row < len(self.filtered_data):
            row = self.filtered_data.iloc[table_row]
            if "見込み利益" in row.index:
                stored_profit = row.get("見込み利益")
        fields = recalculate_profit_fields(
            purchase,
            planned,
            platform,
            ship,
            total,
            stored_profit=stored_profit,
            prefer_stored_profit=cell_has_numeric_value(stored_profit),
        )
        break_even = int(fields["損益分岐点"])
        profit = int(fields["見込み利益"])
        total = int(fields[COL_TOTAL_COST])
        margin = fields["想定利益率"]
        roi = fields["想定ROI"]

        self._profit_recalc_block = True
        try:
            self._write_table_money_cell(table_row, COL_TOTAL_COST, total)
            self._write_table_money_cell(table_row, "損益分岐点", break_even)
            self._write_table_money_cell(table_row, "見込み利益", profit)
            self._write_table_rate_cell(table_row, "想定利益率", margin)
            self._write_table_rate_cell(table_row, "想定ROI", roi)
        finally:
            self._profit_recalc_block = False

        try:
            idx = self.filtered_data.index[table_row]
            for col, val in (
                ("仕入れ価格", purchase),
                ("販売予定価格", planned),
                (COL_PLATFORM_FEE, fee_storage_value(platform)),
                (COL_SHIPPING, fee_storage_value(ship)),
                (COL_TOTAL_COST, fee_storage_value(total)),
                ("損益分岐点", break_even),
                ("見込み利益", profit),
            ):
                if col in self.filtered_data.columns:
                    self.filtered_data.at[idx, col] = val
                if self.inventory_data is not None and idx in self.inventory_data.index and col in self.inventory_data.columns:
                    self.inventory_data.at[idx, col] = val
            for col, val in (("想定利益率", margin), ("想定ROI", roi)):
                if col in self.filtered_data.columns:
                    self.filtered_data.at[idx, col] = val
                if self.inventory_data is not None and idx in self.inventory_data.index and col in self.inventory_data.columns:
                    self.inventory_data.at[idx, col] = val
        except Exception as e:
            print(f"利益再計算のDataFrame同期エラー: {e}")

        try:
            self.update_stats()
        except Exception:
            pass

    def _on_inventory_table_item_changed(self, item: QTableWidgetItem) -> None:
        if getattr(self, "_profit_recalc_block", False):
            return
        if self.filtered_data is None or item is None:
            return
        row = item.row()
        col = item.column()
        if col < 0 or col >= len(self.column_headers):
            return
        col_name = self.column_headers[col]
        if col_name not in (
            "仕入れ価格", "販売予定価格", COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST,
        ):
            return
        if row < 0 or row >= len(self.filtered_data):
            return
        self._recalculate_profit_for_table_row(row)

    def _is_excluded_row(self, row: dict) -> bool:
        """除外条件の判定: コメントに『除外』または 発送方法がFBA以外"""
        try:
            comment = str(row.get('コメント', '') or '')
            if '除外' in comment:
                return True
            ship = str(row.get('発送方法', '') or '').strip().upper()
            if ship == '':
                return True
            return ship != 'FBA'
        except Exception:
            return True

    def toggle_excluded_highlight(self):
        self.excluded_highlight_on = not self.excluded_highlight_on
        if self.excluded_highlight_on:
            self.update_excluded_highlight()
            self.toggle_excluded_btn.setText("除外ハイライト解除")
        else:
            self.clear_excluded_highlight()
            self.toggle_excluded_btn.setText("除外商品確認")

    def update_excluded_highlight(self):
        """除外ではない商品を明確にハイライト（背景＋太字）"""
        try:
            if self.filtered_data is None:
                return
            rows = self.data_table.rowCount()
            for i in range(rows):
                # 現在行の辞書を作成
                row_dict = {}
                for j, column in enumerate(self.column_headers):
                    item = self.data_table.item(i, j)
                    row_dict[column] = item.text() if item else ''
                is_ex = self._is_excluded_row(row_dict)
                for j in range(self.data_table.columnCount()):
                    cell = self.data_table.item(i, j)
                    if not cell:
                        continue
                    if not is_ex:
                        # 除外ではない行を強調（淡い青系）
                        cell.setData(Qt.BackgroundRole, QColor(200, 225, 255))
                        cell.setData(Qt.ForegroundRole, QColor(0, 0, 0))
                        f = cell.font(); f.setBold(True); cell.setFont(f)
                    else:
                        # 除外行は通常表示（交互行色）
                        cell.setData(Qt.BackgroundRole, None)
                        cell.setData(Qt.ForegroundRole, None)
                        f = cell.font(); f.setBold(False); cell.setFont(f)
                        if i % 2 == 0:
                            cell.setBackground(QColor(255, 255, 255))
                        else:
                            cell.setBackground(QColor(240, 240, 240))
        except Exception as e:
            print(f"除外ハイライト更新エラー: {e}")

    def clear_excluded_highlight(self):
        try:
            rows = self.data_table.rowCount()
            for i in range(rows):
                for j in range(self.data_table.columnCount()):
                    cell = self.data_table.item(i, j)
                    if not cell:
                        continue
                    cell.setData(Qt.BackgroundRole, None)
                    cell.setData(Qt.ForegroundRole, None)
                    f = cell.font(); f.setBold(False); cell.setFont(f)
                    if i % 2 == 0:
                        cell.setBackground(QColor(255, 255, 255))
                    else:
                        cell.setBackground(QColor(240, 240, 240))
        except Exception as e:
            print(f"除外ハイライト解除エラー: {e}")

    def apply_filters(self):
        """フィルタの適用"""
        if self.inventory_data is None:
            return
            
        # 検索条件
        search_text = self.search_edit.text().lower()
        
        # Q列フィルタ（存在する場合のみ）
        q_filter = ""
        if hasattr(self, 'q_filter_combo') and self.q_filter_combo:
            q_filter = self.q_filter_combo.currentText()
        
        # 価格範囲フィルタ
        min_price = self.min_price_spin.value()
        max_price = self.max_price_spin.value()
        
        # フィルタの適用
        mask = pd.Series([True] * len(self.inventory_data))
        
        # 検索フィルタ
        if search_text:
            search_mask = (
                self.inventory_data.get("商品名", "").str.lower().str.contains(search_text, na=False) |
                self.inventory_data.get("ASIN", "").str.lower().str.contains(search_text, na=False) |
                self.inventory_data.get("JAN", "").str.lower().str.contains(search_text, na=False)
            )
            mask &= search_mask
        
        # Q列フィルタ（Q列は現在の列構成に含まれていないため、一旦コメントアウト）
        # if q_filter != "すべて":
        #     if q_filter == "Qなし":
        #         q_mask = self.inventory_data.get("Q列", "").isna() | (self.inventory_data.get("Q列", "") == "")
        #     else:
        #         q_mask = self.inventory_data.get("Q列", "") == q_filter
        #     mask &= q_mask
        
        # 価格範囲フィルタ（販売予定価格でフィルタ）
        if "販売予定価格" in self.inventory_data.columns:
            try:
                price_series = pd.to_numeric(self.inventory_data["販売予定価格"], errors='coerce')
                price_mask = (price_series >= min_price) & (price_series <= max_price)
                mask &= price_mask
            except:
                pass
        
        # フィルタ結果の適用
        self.filtered_data = self.inventory_data[mask].copy()
        
        # テーブルの更新
        self.update_table()
        self.update_data_count()

    def clear_search(self):
        """検索のクリア"""
        self.search_edit.clear()

    def reset_filters(self):
        """フィルタのリセット"""
        self.search_edit.clear()
        # self.q_filter_combo.setCurrentText("すべて")  # Q列フィルタは非表示
        self.min_price_spin.setValue(0)
        self.max_price_spin.setValue(999999)

    def on_data_selection_changed(self):
        """データテーブルの選択変更時の処理（商品名列のハイライト）"""
        try:
            # 選択された行を取得
            selected_items = self.data_table.selectedItems()
            
            # 行削除ボタンの有効/無効を制御
            has_selection = len(selected_items) > 0
            if hasattr(self, 'data_delete_row_btn'):
                self.data_delete_row_btn.setEnabled(has_selection)
            
            if not selected_items:
                return
            
            # 最初の選択されたアイテムの行番号を取得
            current_row = selected_items[0].row()
            
            # 商品名列を探す
            product_name_column = -1
            for j in range(self.data_table.columnCount()):
                header_item = self.data_table.horizontalHeaderItem(j)
                if header_item and header_item.text() == '商品名':
                    product_name_column = j
                    break
            
            # 商品名列が見つかった場合、その列をハイライト
            if product_name_column >= 0:
                # 商品名列のセルをハイライト
                    for j in range(self.data_table.columnCount()):
                        row_item = self.data_table.item(current_row, j)
                        if row_item:
                            if j == product_name_column:
                                # 商品名列は黄色でハイライト
                                row_item.setBackground(QColor(255, 255, 200))
                            else:
                                # 他の列は通常の背景色（交互行色を維持）
                                if current_row % 2 == 0:
                                    row_item.setBackground(QColor(255, 255, 255))
                                else:
                                    row_item.setBackground(QColor(240, 240, 240))
                                    
        except Exception as e:
            print(f"選択変更処理エラー: {e}")

    def _get_row_data_for_edit(self, table_row_index: int) -> Dict[str, Any]:
        """テーブルの指定行から編集用の行データを取得（商品名はUserRoleを優先）"""
        row_data = {}
        for j, column in enumerate(self.column_headers):
            if j >= self.data_table.columnCount():
                break
            item = self.data_table.item(table_row_index, j)
            value = item.text() if item else ""
            if column == "商品名" and item is not None:
                full = item.data(Qt.UserRole)
                if full is not None and str(full).strip():
                    value = str(full)
            if column == "コンディション説明":
                value = _normalize_condition_note_newlines(value)
            if column == "価格改定" and not str(value).strip():
                value = "ON"
            if column == "発送方法" and not str(value).strip():
                value = "FBA"
            if column == "販売チャネル" and not str(value).strip():
                value = "Amazon"
            row_data[column] = value
        return row_data

    def _apply_edited_row_to_table(self, table_row_index: int, result: Dict[str, Any]):
        """編集結果をテーブルの指定行に反映し、filtered_data / inventory_data も更新する"""
        self.data_table.blockSignals(True)
        try:
            for j, column in enumerate(self.column_headers):
                if j >= self.data_table.columnCount():
                    break
                value = result.get(column, "")
                if value is None:
                    value = ""
                value = str(value)
                item = self.data_table.item(table_row_index, j)
                if not item:
                    item = QTableWidgetItem(value)
                    self.data_table.setItem(table_row_index, j, item)
                else:
                    item.setText(value)
                if column == "商品名":
                    item.setToolTip(value)
                    item.setData(Qt.UserRole, value)
                    item.setText(value[:50] + "..." if len(value) > 50 else value)
                if column == "SKU":
                    item.setData(Qt.UserRole, value)  # フルSKUを保持（保存時に使用）
                if column == "コンディション説明":
                    item.setToolTip(_normalize_condition_note_newlines(value))
        finally:
            self.data_table.blockSignals(False)
        # filtered_data / inventory_data をテーブルから再取得して同期
        df = self.get_table_data()
        if df is not None and len(df) > 0 and self.filtered_data is not None:
            # 現在の filtered_data のインデックス構造を維持して更新
            try:
                idx = self.filtered_data.index[table_row_index]
                for col in self.column_headers:
                    if col in df.columns and col in self.filtered_data.columns:
                        val = df.iloc[table_row_index][col]
                        # SKUが省略表示(...)の場合は上書きしない（本番と同じフル値を維持）
                        if col == "SKU" and isinstance(val, str) and val.strip().endswith("..."):
                            continue
                        self.filtered_data.at[idx, col] = val
                if self.inventory_data is not None and idx in self.inventory_data.index:
                    for col in self.column_headers:
                        if col in df.columns and col in self.inventory_data.columns:
                            val = df.iloc[table_row_index][col]
                            if col == "SKU" and isinstance(val, str) and val.strip().endswith("..."):
                                continue
                            self.inventory_data.at[idx, col] = val
            except Exception as e:
                # フォールバック: テーブル全体で上書き
                self.filtered_data = df.copy()
                self.inventory_data = df.copy()

    def _on_data_row_double_clicked(self, item: QTableWidgetItem):
        """仕入データ一覧の行をダブルクリックしたときに編集ダイアログを開く"""
        if item is None:
            return
        row_index = item.row()
        if row_index < 0 or (self.filtered_data is not None and row_index >= len(self.filtered_data)):
            return
        row_data = self._get_row_data_for_edit(row_index)
        dlg = InventoryRowEditDialog(
            self.column_headers,
            row_data,
            self.condition_template_db,
            self._get_condition_key,
            self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            self._apply_edited_row_to_table(row_index, result)
            # 一覧と同じ損益式で見込み利益・損益分岐点・率を揃える
            self._recalculate_profit_for_table_row(row_index)

    def update_data_count(self):
        """データ件数の更新"""
        if self.filtered_data is not None:
            total_count = len(self.inventory_data) if self.inventory_data is not None else 0
            filtered_count = len(self.filtered_data)
            self.data_count_label.setText(f"データ件数: {filtered_count}/{total_count}")
            
            # 統計情報の更新
            self.update_stats()
        else:
            self.data_count_label.setText("データ件数: 0")

    def update_stats(self):
        """統計情報の更新"""
        if self.filtered_data is None or len(self.filtered_data) == 0:
            self.stats_label.setText("統計: なし")
            return

        # 基本統計
        total_items = len(self.filtered_data)

        # コンディション統計
        try:
            if "コンディション" in self.filtered_data.columns:
                condition_counts = self.filtered_data["コンディション"].value_counts()
                condition_stats = ", ".join([f"{cond}: {count}" for cond, count in condition_counts.items() if cond])
            else:
                condition_stats = "コンディション: なし"
        except Exception as e:
            print(f"コンディション統計エラー: {e}")
            condition_stats = "コンディション: エラー"
        
        # 価格統計（販売予定価格で統計）
        try:
            if "販売予定価格" in self.filtered_data.columns:
                prices = pd.to_numeric(self.filtered_data["販売予定価格"], errors='coerce')
                avg_price = prices.mean()
                total_value = prices.sum()
                price_stats = f"平均価格: {avg_price:,.0f}円, 合計: {total_value:,.0f}円"
            else:
                price_stats = "価格統計: なし"
        except Exception as e:
            print(f"価格統計エラー: {e}")
            price_stats = "価格統計: エラー"

        stats_text = f"統計: {total_items}件, {condition_stats}, {price_stats}"

        # PRO版かつ開発タブの場合のみ、仕入健全度スコア（件数ベース/利益ベース）を計算して表示
        count_health = None
        profit_health = None
        if getattr(self, "dev_mode", False) and is_pro_enabled():
            try:
                count_health = self._compute_health_score_3_6_9(self.filtered_data)
            except Exception as e:
                print(f"仕入健全度スコア計算エラー(件数): {e}")
                count_health = None
            try:
                profit_health = self._compute_health_score_3_6_9_profit(self.filtered_data)
            except Exception as e:
                print(f"仕入健全度スコア計算エラー(利益): {e}")
                profit_health = None

        # 仕入健全度（件数ベース）
        if count_health:
            ratio_3, ratio_6, ratio_9 = count_health["ratio_3"], count_health["ratio_6"], count_health["ratio_9"]
            level = count_health["level"]
            stats_text = (
                f"{stats_text}, "
                f"仕入健全度(件数3-6-9): {ratio_3}:{ratio_6}:{ratio_9}（{level}）"
            )

        # 仕入健全度（利益ベース）＋実効見込み利益
        final_color = ""
        if profit_health:
            pr3, pr6, pr9 = profit_health["ratio_3"], profit_health["ratio_6"], profit_health["ratio_9"]
            plevel = profit_health["level"]
            eff_rate = profit_health["effective_rate"]
            total_profit = profit_health["total_profit"]
            effective_profit = profit_health["effective_profit"]
            stats_text = (
                f"{stats_text}, "
                f"仕入健全度(金額3-6-9): {pr3}:{pr6}:{pr9}（{plevel}）, "
                f"実効見込み利益: {effective_profit:,.0f}円 / 想定見込み利益 {total_profit:,.0f}円 "
                f"(実現率 {eff_rate:,.1f}%)"
            )
            final_color = profit_health["color"]

        # ラベル色は「より危険側」の色を優先（利益ベース＞件数ベース）
        if profit_health:
            self.stats_label.setStyleSheet(f"color: {profit_health['color']};")
        elif count_health:
            self.stats_label.setStyleSheet(f"color: {count_health['color']};")
        else:
            # 通常の統計表示（色はデフォルトに戻す）
            self.stats_label.setStyleSheet("")

        self.stats_label.setText(stats_text)

    def _compute_health_score_3_6_9(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        コメント列に入力された数値から 3-6-9 比率を算出し、
        仕入健全度スコア情報を返す（開発タブ用 / PRO版限定）。
        """
        if df is None or "コメント" not in df.columns:
            return None

        counts = {"3": 0, "6": 0, "9": 0}
        import math
        for v in df["コメント"]:
            # コメント無し（NaN/None/空文字）は 6 判定
            if v is None or (isinstance(v, float) and math.isnan(v)):
                bucket = "6"
            else:
                text = str(v).strip()
                # 「除外」「テスト」を含む行は仕入健全度の統計から除外
                if "除外" in text or "テスト" in text:
                    continue
                if text == "":
                    bucket = "6"
                else:
                    # 先頭の1〜2桁の数字からグループ判定し、取れなければ 6 とみなす
                    classified = self._classify_health_bucket(text)
                    bucket = classified if classified in counts else "6"

            counts[bucket] += 1

        total = counts["3"] + counts["6"] + counts["9"]
        if total == 0:
            return None

        # 割合（%）を整数で算出し、合計が100になるように最後の値で調整
        r3_float = counts["3"] * 100.0 / total
        r6_float = counts["6"] * 100.0 / total
        r9_float = counts["9"] * 100.0 / total

        r3 = int(round(r3_float))
        r6 = int(round(r6_float))
        r9 = 100 - r3 - r6
        if r9 < 0:
            r9 = 0

        # R9(9グループ比率) に基づいて診断レベルを判定
        # 〜15%: 安全（グリーン）、〜25%: 注意（イエロー）、それ以上: 危険（レッド）
        if r9 <= 15:
            level = "安全圏"
            color = "#4caf50"  # Green
        elif r9 <= 25:
            level = "注意圏"
            color = "#ffc107"  # Yellow
        else:
            level = "危険域"
            color = "#f44336"  # Red

        return {
            "ratio_3": r3,
            "ratio_6": r6,
            "ratio_9": r9,
            "level": level,
            "color": color,
        }

    def _compute_health_score_3_6_9_profit(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        コメント列の3/6/9分類と「見込み利益」から、
        利益金額ベースの3-6-9比率と実効見込み利益を計算する。
        """
        if df is None or "コメント" not in df.columns or "見込み利益" not in df.columns:
            return None

        import math
        # グループごとの理論見込み利益合計と実効見込み利益合計
        base_profit = {"3": 0.0, "6": 0.0, "9": 0.0}
        eff_profit = {"3": 0.0, "6": 0.0, "9": 0.0}

        for _, row in df.iterrows():
            comment_val = row.get("コメント")
            # コメントが空欄/NaN の場合は 6 グループ
            if comment_val is None or (isinstance(comment_val, float) and math.isnan(comment_val)):
                bucket = "6"
            else:
                text = str(comment_val).strip()
                # 「除外」「テスト」を含む行は利益計算から除外
                if "除外" in text or "テスト" in text:
                    continue
                if text == "":
                    bucket = "6"
                else:
                    classified = self._classify_health_bucket(text)
                    # 先頭の1〜2桁から判定し、取れない/想定外はすべて 6 とみなす
                    bucket = classified if classified in base_profit else "6"

            profit_val = row.get("見込み利益", 0)
            try:
                profit = float(profit_val)
            except Exception:
                profit = 0.0
            if profit <= 0:
                continue

            qty = self._row_quantity_multiplier(row)
            if qty <= 0:
                continue

            weighted_profit = profit * qty
            base_profit[bucket] += weighted_profit
            # 発送方法に応じて係数を切り替える
            shipping = str(row.get("発送方法", "") or "").strip()
            is_fba = "fba" in shipping.upper() if shipping else False
            if bucket == "3":
                z = 0.9
            elif bucket == "6":
                z = 0.7
            elif bucket == "9":
                # 9グループは FBA長期在庫なら0.6、自己発送(非FBA)なら送料のみを見て0.9
                z = 0.6 if is_fba else 0.9
            else:
                # 想定外は6グループ相当として扱う
                z = 0.7

            eff_profit[bucket] += weighted_profit * z

        total_base = base_profit["3"] + base_profit["6"] + base_profit["9"]
        total_eff = eff_profit["3"] + eff_profit["6"] + eff_profit["9"]
        if total_base <= 0 or total_eff <= 0:
            return None

        # 実効見込み利益のグループ比率（%）
        r3_float = eff_profit["3"] * 100.0 / total_eff
        r6_float = eff_profit["6"] * 100.0 / total_eff
        r9_float = eff_profit["9"] * 100.0 / total_eff

        r3 = int(round(r3_float))
        r6 = int(round(r6_float))
        r9 = 100 - r3 - r6
        if r9 < 0:
            r9 = 0

        # 9ヶ月グループの比率で診断レベルを判定（件数ベースと同じ閾値）
        if r9 <= 15:
            level = "安全圏"
            color = "#4caf50"  # Green
        elif r9 <= 25:
            level = "注意圏"
            color = "#ffc107"  # Yellow
        else:
            level = "危険域"
            color = "#f44336"  # Red

        # 実効見込み利益率（理論見込み利益合計に対する実効利益の割合）
        effective_rate = (total_eff / total_base) * 100.0

        return {
            "ratio_3": r3,
            "ratio_6": r6,
            "ratio_9": r9,
            "level": level,
            "color": color,
            "total_profit": total_base,
            "effective_profit": total_eff,
            "effective_rate": effective_rate,
        }

    def _classify_health_bucket(self, comment: str) -> Optional[str]:
        """
        コメント文字列から 3/6/9 グループを判定して返す。
        例: 3, 4, 3n -> '3' / 6, 7, 6n -> '6' / 9, 10, 9n -> '9'
        （3p/3n, 6p/6n, 9p/9n の違いはここでは区別しない）
        """
        if not comment:
            return None
        s = str(comment).strip().lower()
        if not s:
            return None

        import re
        # 最初に現れる1〜2桁の数字を取り出して判定する
        m = re.search(r"(\d{1,2})", s)
        if not m:
            return None

        try:
            n = int(m.group(1))
        except ValueError:
            return None

        # 3/4 → 3グループ, 6/7 → 6グループ, 9/10 → 9グループ
        if n in (3, 4):
            return "3"
        if n in (6, 7):
            return "6"
        if n in (9, 10):
            return "9"
        # 想定外の数字（11以上など）は分類不能 → 呼び出し側で 6 扱い
        return None

    def _infer_rule369_from_comment(self, comment: Any) -> str:
        """
        コメント文字列から 3P/3N/6P/6N/9P/9N コードを判定して返す。
        ルールは services/sku_template.py の SKUTemplateRenderer._get_rule369_code と同一:
        - 3          → 3P
        - 4, 3n      → 3N
        - 6          → 6P
        - 7, 6n      → 6N
        - 9          → 9P
        - 10, 9n     → 9N
        - 空欄や上記以外（11,12...などの連番を含む）→ 6P
        """
        try:
            s = "" if comment is None else str(comment).strip().lower()
        except Exception:
            s = ""

        if not s:
            return "6P"

        import re
        # 先頭トークン（数字・pnコード）だけを見る
        # 例: "3", "4", "3n", "6p", "9n", "10", "3n-テスト" など
        m = re.match(r"^(3n|3p|6n|6p|9n|9p|10|3|4|6|7|9)\b", s)
        if not m:
            return "6P"

        code = m.group(1)

        if code in ("3", "3p"):
            return "3P"
        if code in ("4", "3n"):
            return "3N"
        if code in ("6", "6p"):
            return "6P"
        if code in ("7", "6n"):
            return "6N"
        if code in ("9", "9p"):
            return "9P"
        if code in ("10", "9n"):
            return "9N"

        # 想定外はすべて 6P 扱い
        return "6P"

    def _show_stats_help_dialog(self):
        """
        統計エリア右側の「?」ボタンから呼び出されるヘルプダイアログ。
        仕入健全度(3-6-9) と実効見込み利益の計算方法を簡潔に説明する。
        """
        try:
            msg = (
                "【仕入健全度(件数3-6-9)】\n"
                "・コメント列に 3 / 6 / 9（または 4,7,10,3n,6n,9n,3p,6p,9p）などの単一コードを入力して、\n"
                "  それぞれ「3ヶ月以内 / 6ヶ月以内 / 9ヶ月コース」のグループに分類します。\n"
                "・空欄は 6 として扱います。\n"
                "・各グループの件数比率 3:6:9(%) を集計し、9グループが\n"
                "    15%以下 → 安全圏 / 15〜25% → 注意圏 / 25%以上 → 危険域 と判定します。\n"
                "\n"
                "【仕入健全度(金額3-6-9)】\n"
                "・上記と同じ3/6/9分類を使いながら、「見込み利益 × 仕入れ個数」の金額で重み付けします。\n"
                "・各行ごとに、コメントから 3/6/9 を決めたあと、\n"
                "    3グループ: 見込み利益 × 0.9\n"
                "    6グループ: 見込み利益 × 0.7\n"
                "    9グループ: 発送方法がFBAなら ×0.6 / それ以外(自己発送など)は ×0.9\n"
                "  として値崩れ・保管料・送料を織り込んだ実効見込み利益を計算します。\n"
                "・3:6:9 = 実効見込み利益の比率(%) を表示し、9グループ比率の閾値は件数ベースと同じです。\n"
                "\n"
                "【実効見込み利益】\n"
                "・想定見込み利益合計 = 全行の（見込み利益 × 仕入れ個数）の合計（除外・テストを除く）\n"
                "・実効見込み利益合計 = 各行の「見込み利益 × 仕入れ個数 × 上記の係数」を足し合わせた値\n"
                "・実現率(%) = 実効見込み利益合計 ÷ 想定見込み利益合計 × 100\n"
                "  （= 値崩れ・保管料・送料を加味した現実的な期待利益率）\n"
            )
            QMessageBox.information(self, "仕入健全度と実効利益の計算式", msg)
        except Exception as e:
            print(f"統計ヘルプダイアログ表示エラー: {e}")

    def clear_data(self):
        """データのクリア（仕入データ一覧とルート情報の両方をクリア）"""
        # 仕入データのクリア
        self.inventory_data = None
        self.filtered_data = None
        self.data_table.setRowCount(0)
        
        # ルート情報のクリア
        self.route_template_table.setRowCount(0)
        self.route_template_summary_label.setText("ルート情報: ー")
        
        # ルートサマリーウィジェットのデータもクリア（可能であれば）
        if self.route_summary_widget:
            try:
                # ルートサマリーウィジェットのデータをクリア
                if hasattr(self.route_summary_widget, 'clear_route_data'):
                    self.route_summary_widget.clear_route_data()
                elif hasattr(self.route_summary_widget, 'current_route_id'):
                    self.route_summary_widget.current_route_id = None
            except Exception as e:
                print(f"ルート情報のクリア中にエラー: {e}")
        
        # ボタンの無効化
        self.export_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        if hasattr(self, "clear_sku_btn"):
            self.clear_sku_btn.setEnabled(False)
        self.generate_sku_btn.setEnabled(False)
        self.export_listing_btn.setEnabled(False)
        self.antique_register_btn.setEnabled(False)
        
        # 表示のクリア
        self.data_count_label.setText("データ件数: 0")
        self.stats_label.setText("統計: なし")
        
        # 各エリアのボタンも無効化
        if hasattr(self, 'data_clear_btn'):
            self.data_clear_btn.setEnabled(False)
        if hasattr(self, 'data_delete_row_btn'):
            self.data_delete_row_btn.setEnabled(False)
        if hasattr(self, 'route_clear_btn'):
            self.route_clear_btn.setEnabled(False)
        if hasattr(self, 'route_delete_row_btn'):
            self.route_delete_row_btn.setEnabled(False)

        self._update_workflow_status("ワークフロー: 未実行", emphasize=False)
        self._set_listing_csv_drag_file("")

    def clear_inventory_data(self):
        """仕入データ一覧のみをクリア"""
        reply = QMessageBox.question(
            self,
            "確認",
            "仕入データ一覧をクリアしますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.inventory_data = None
            self.filtered_data = None
            self.data_table.setRowCount(0)
            
            # ボタンの無効化
            self.export_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            if hasattr(self, "clear_sku_btn"):
                self.clear_sku_btn.setEnabled(False)
            self.generate_sku_btn.setEnabled(False)
            self.export_listing_btn.setEnabled(False)
            self.antique_register_btn.setEnabled(False)
            if hasattr(self, 'data_clear_btn'):
                self.data_clear_btn.setEnabled(False)
            if hasattr(self, 'data_delete_row_btn'):
                self.data_delete_row_btn.setEnabled(False)
            
            # 表示のクリア
            self.data_count_label.setText("データ件数: 0")
            self.stats_label.setText("統計: なし")

    def delete_selected_inventory_rows(self):
        """選択された仕入データの行を削除"""
        selected_rows = set()
        for item in self.data_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            QMessageBox.warning(self, "警告", "削除する行を選択してください")
            return
        
        reply = QMessageBox.question(
            self,
            "確認",
            f"{len(selected_rows)}行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 行番号を降順にソート（後ろから削除することでインデックスがずれない）
            sorted_rows = sorted(selected_rows, reverse=True)
            
            # filtered_dataから削除
            if self.filtered_data is not None:
                indices_to_drop = [self.filtered_data.index[i] for i in sorted_rows if i < len(self.filtered_data)]
                self.filtered_data = self.filtered_data.drop(indices_to_drop)
                self.filtered_data = self.filtered_data.reset_index(drop=True)
            
            # inventory_dataからも削除（該当する行を探して削除）
            if self.inventory_data is not None:
                # テーブルの行番号とinventory_dataのインデックスを対応させる
                for row_idx in sorted_rows:
                    if row_idx < len(self.filtered_data) if self.filtered_data is not None else False:
                        # filtered_dataのインデックスを使ってinventory_dataからも削除
                        if self.filtered_data is not None and row_idx < len(self.filtered_data):
                            # 実際のデータはupdate_tableで再構築されるので、ここではテーブルから削除のみ
                            pass
            
            # テーブルから行を削除
            for row_idx in sorted_rows:
                self.data_table.removeRow(row_idx)
            
            # テーブルを更新
            self.update_table()
            self.update_stats()
            
            # ボタンの有効/無効を更新
            if self.data_table.rowCount() == 0:
                if hasattr(self, 'data_clear_btn'):
                    self.data_clear_btn.setEnabled(False)
                if hasattr(self, 'data_delete_row_btn'):
                    self.data_delete_row_btn.setEnabled(False)

    def get_table_data(self) -> pd.DataFrame:
        """テーブルから現在のデータを取得してDataFrameに変換"""
        try:
            row_count = self.data_table.rowCount()
            if row_count == 0:
                return pd.DataFrame()
            
            # テーブルのデータをリストに収集
            data_rows = []
            for i in range(row_count):
                row_data = {}
                for j, column in enumerate(self.column_headers):
                    item = self.data_table.item(i, j)
                    value = item.text() if item else ""
                    # 商品名はUserRoleに保持したフルテキストを優先
                    if column == "商品名" and item is not None:
                        full = item.data(Qt.UserRole)
                        if full is not None and str(full).strip():
                            value = str(full)
                        # UserRoleが空の場合は、表示テキストから「...」を除去して使用（既存データ対応）
                        elif value.endswith('...'):
                            # 表示テキストが50文字+「...」の場合は、元のデータを探す
                            # ただし、既に切られている場合は復元できない
                            pass
                    
                    # 数値列の特別処理（カンマ区切りを除去）
                    if column in [
                        "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "仕入れ個数",
                        COL_PLATFORM_FEE, COL_SHIPPING, COL_TOTAL_COST, "在庫保管手数料",
                    ]:
                        try:
                            # カンマを除去して数値に変換
                            value_str = str(value).replace(",", "").strip()
                            if value_str == "" or value_str == "未実装" or value_str == "nan" or pd.isna(value):
                                row_data[column] = None
                            else:
                                # 数値に変換を試みる
                                if "." in value_str:
                                    row_data[column] = float(value_str)
                                else:
                                    row_data[column] = int(value_str)
                        except (ValueError, TypeError) as e:
                            # 変換に失敗した場合は元の値をそのまま使用
                            row_data[column] = value
                    # 利益率とROIの特別処理（小数点第2位まで）
                    elif column in ["想定利益率", "想定ROI"]:
                        try:
                            value_str = str(value).replace(",", "").strip()
                            if value_str == "" or value_str == "nan" or pd.isna(value):
                                row_data[column] = 0.0
                            else:
                                row_data[column] = round(float(value_str), 2)
                        except (ValueError, TypeError):
                            row_data[column] = 0.0
                    # SKU列の特別処理（UserRoleにフル値を保持している場合はそれを優先、「未実装」は空文字に変換）
                    elif column == "SKU":
                        if item is not None:
                            full_sku = item.data(Qt.UserRole)
                            if full_sku is not None and str(full_sku).strip():
                                value = str(full_sku)
                        if value == "未実装":
                            row_data[column] = ""
                        else:
                            row_data[column] = value
                    else:
                        row_data[column] = value
                
                data_rows.append(row_data)
            
            # DataFrameに変換
            df = pd.DataFrame(data_rows)
            
            # 列の順序を維持
            if len(df) > 0:
                df = df[self.column_headers]
            
            return df
            
        except Exception as e:
            print(f"テーブルデータ取得エラー: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()

    def sync_inventory_data_from_table(self):
        """テーブルの内容をinventory_dataに同期"""
        try:
            # テーブルからデータを取得
            table_df = self.get_table_data()
            
            if len(table_df) == 0:
                return False
            
            # フィルタが適用されていない場合は、テーブルのデータをそのまま使用
            # フィルタが適用されている場合も、テーブルに表示されているデータを
            # inventory_dataとして使用する（照合再計算では表示されているデータのみを対象とする）
            self.inventory_data = table_df.copy()
            self.filtered_data = table_df.copy()
            
            return True
            
        except Exception as e:
            print(f"inventory_data同期エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

