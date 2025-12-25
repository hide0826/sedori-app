#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品データベース閲覧・編集ウィジェット
"""
from __future__ import annotations

import sys
import os
import re
import unicodedata
import calendar
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import copy

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel, QTabWidget, QHeaderView, QFileDialog, QMenu, QApplication,
    QAbstractItemView, QComboBox
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor

from desktop.utils.ui_utils import (
    save_table_header_state, restore_table_header_state,
    save_table_column_widths, restore_table_column_widths
)

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import json
import logging
from database.product_db import ProductDatabase
from database.warranty_db import WarrantyDatabase
from database.product_purchase_db import ProductPurchaseDatabase
from database.purchase_db import PurchaseDatabase  # 古物台帳情報の参照用
from database.store_db import StoreDatabase

class SortableDateItem(QTableWidgetItem):
    """日付ソート対応のQTableWidgetItem"""
    
    def __init__(self, text: str, sort_value: float = 0.0):
        super().__init__(text)
        self.sort_value = sort_value
    
    def __lt__(self, other):
        """ソート時の比較処理"""
        if isinstance(other, SortableDateItem):
            return self.sort_value < other.sort_value
        return super().__lt__(other)


class DraggableTableWidget(QTableWidget):
    """ドラッグアンドドロップ対応のQTableWidget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # マウストラッキングを有効化（カーソル変更用）
        self.setMouseTracking(True)
    
    def mouseMoveEvent(self, event):
        """マウス移動時の処理（カーソル変更用）"""
        item = self.itemAt(event.position().toPoint())
        if item:
            col = self.column(item)
            header = self.horizontalHeaderItem(col)
            if header:
                header_text = header.text()
                if (header_text == "レシート画像" or header_text == "保証書画像") and item.text().strip():
                    self.setCursor(QCursor(Qt.PointingHandCursor))
                else:
                    self.setCursor(QCursor(Qt.ArrowCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))
        super().mouseMoveEvent(event)
    
    def startDrag(self, supportedActions):
        """ドラッグ開始時の処理"""
        item = self.currentItem()
        if item is None:
            return super().startDrag(supportedActions)
        
        # レシート画像列または保証書画像列かどうかを確認
        col = self.currentColumn()
        header = self.horizontalHeaderItem(col)
        if header:
            header_text = header.text()
            if header_text == "レシート画像" or header_text == "保証書画像":
                image_name = item.text().strip()
                if image_name:
                    # ドラッグデータを作成
                    drag = QDrag(self)
                    mime_data = QMimeData()
                    # テキストデータとして画像名を設定
                    mime_data.setText(image_name)
                    drag.setMimeData(mime_data)
                    # ドラッグを開始
                    drag.exec_(Qt.CopyAction)
                    return
        # レシート画像列・保証書画像列以外は通常のドラッグ処理
        super().startDrag(supportedActions)


class ProductEditDialog(QDialog):
    """商品情報の編集ダイアログ"""

    def __init__(self, parent=None, product: Optional[dict] = None):
        super().__init__(parent)
        self.product = product or {}
        self.db = ProductDatabase()
        self.image_edits = []  # 初期化
        self.setWindowTitle("商品編集" if product else "商品追加")
        self.setup_ui()
        if product:
            self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        form_group = QGroupBox("商品情報")
        form_layout = QFormLayout(form_group)

        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("必須。例: 20250201-A1234")
        form_layout.addRow("SKU:", self.sku_edit)

        self.jan_edit = QLineEdit()
        form_layout.addRow("JAN:", self.jan_edit)

        self.asin_edit = QLineEdit()
        form_layout.addRow("ASIN:", self.asin_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("商品名を入力")
        form_layout.addRow("商品名:", self.name_edit)

        self.purchase_date_edit = QLineEdit()
        self.purchase_date_edit.setPlaceholderText("yyyy-mm-dd")
        form_layout.addRow("仕入日:", self.purchase_date_edit)

        self.purchase_price_edit = QLineEdit()
        form_layout.addRow("仕入価格:", self.purchase_price_edit)

        self.quantity_edit = QLineEdit()
        form_layout.addRow("数量:", self.quantity_edit)

        self.store_code_edit = QLineEdit()
        form_layout.addRow("店舗コード:", self.store_code_edit)

        self.store_name_edit = QLineEdit()
        form_layout.addRow("店舗名:", self.store_name_edit)

        self.warranty_days_edit = QLineEdit()
        form_layout.addRow("保証期間(日):", self.warranty_days_edit)

        self.warranty_until_edit = QLineEdit()
        self.warranty_until_edit.setPlaceholderText("yyyy-mm-dd")
        form_layout.addRow("保証満了日:", self.warranty_until_edit)

        layout.addWidget(form_group)
        
        # 画像グループ（画像1〜6）
        image_group = QGroupBox("画像")
        image_layout = QVBoxLayout(image_group)
        
        self.image_edits = []
        for i in range(1, 7):
            row_layout = QHBoxLayout()
            label = QLabel(f"画像{i}:")
            image_edit = QLineEdit()
            image_edit.setPlaceholderText("画像ファイルパスを選択してください")
            select_btn = QPushButton("選択")
            select_btn.clicked.connect(lambda checked, idx=i: self.select_image(idx))
            clear_btn = QPushButton("クリア")
            clear_btn.clicked.connect(lambda checked, idx=i: self.clear_image(idx))
            preview_btn = QPushButton("プレビュー")
            preview_btn.clicked.connect(lambda checked, idx=i: self.preview_image(idx))
            
            row_layout.addWidget(label)
            row_layout.addWidget(image_edit, stretch=1)
            row_layout.addWidget(select_btn)
            row_layout.addWidget(clear_btn)
            row_layout.addWidget(preview_btn)
            image_layout.addLayout(row_layout)
            
            self.image_edits.append(image_edit)
        
        layout.addWidget(image_group)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def select_image(self, index: int):
        """画像ファイルを選択"""
        current_path = self.image_edits[index - 1].text().strip()
        initial_dir = str(Path(current_path).parent) if current_path and Path(current_path).parent.exists() else ""
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"画像{index}を選択",
            initial_dir,
            "画像ファイル (*.jpg *.jpeg *.png *.gif *.bmp);;すべてのファイル (*)"
        )
        
        if file_path:
            self.image_edits[index - 1].setText(file_path)
    
    def clear_image(self, index: int):
        """画像をクリア"""
        self.image_edits[index - 1].clear()
    
    def preview_image(self, index: int):
        """画像をプレビュー"""
        image_path = self.image_edits[index - 1].text().strip()
        if not image_path:
            QMessageBox.information(self, "情報", f"画像{index}が設定されていません。")
            return
        
        file_path = Path(image_path)
        if not file_path.exists():
            QMessageBox.warning(self, "エラー", f"画像ファイルが見つかりません:\n{image_path}")
            return
        
        # 画像ファイルを開く
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))

    def load_data(self):
        self.sku_edit.setText(self.product.get("sku") or "")
        self.sku_edit.setReadOnly(True)
        self.jan_edit.setText(self.product.get("jan") or "")
        self.asin_edit.setText(self.product.get("asin") or "")
        self.name_edit.setText(self.product.get("product_name") or "")
        self.purchase_date_edit.setText(self.product.get("purchase_date") or "")
        self.purchase_price_edit.setText(str(self.product.get("purchase_price") or ""))
        self.quantity_edit.setText(str(self.product.get("quantity") or ""))
        self.store_code_edit.setText(self.product.get("store_code") or "")
        self.store_name_edit.setText(self.product.get("store_name") or "")
        self.warranty_days_edit.setText(str(self.product.get("warranty_period_days") or ""))
        self.warranty_until_edit.setText(self.product.get("warranty_until") or "")
        
        # 画像1〜6を読み込み
        for i in range(1, 7):
            image_key = f"image_{i}"
            image_path = self.product.get(image_key) or ""
            self.image_edits[i - 1].setText(image_path)

    def get_data(self) -> dict:
        sku = self.sku_edit.text().strip()
        if not sku:
            QMessageBox.warning(self, "入力エラー", "SKUは必須です。")
            return {}

        def _to_int(text: str) -> Optional[int]:
            text = text.strip()
            if not text:
                return None
            try:
                return int(text)
            except ValueError:
                return None

        result = {
            "sku": sku,
            "jan": self.jan_edit.text().strip() or None,
            "asin": self.asin_edit.text().strip() or None,
            "product_name": self.name_edit.text().strip() or None,
            "purchase_date": self.purchase_date_edit.text().strip() or None,
            "purchase_price": _to_int(self.purchase_price_edit.text()),
            "quantity": _to_int(self.quantity_edit.text()),
            "store_code": self.store_code_edit.text().strip() or None,
            "store_name": self.store_name_edit.text().strip() or None,
            "warranty_period_days": _to_int(self.warranty_days_edit.text()),
            "warranty_until": self.warranty_until_edit.text().strip() or None,
        }
        
        # 画像1〜6を追加
        for i in range(1, 7):
            image_key = f"image_{i}"
            image_path = self.image_edits[i - 1].text().strip() or None
            result[image_key] = image_path
        
        return result


PRODUCT_NAME_DISPLAY_LIMIT = 50


class ProductWidget(QWidget):
    """商品データ＋仕入/販売DBタブ"""

    def __init__(self, parent=None, inventory_widget=None):
        super().__init__(parent)
        self.db = ProductDatabase()
        self.warranty_db = WarrantyDatabase()
        self.purchase_db = ProductPurchaseDatabase()  # スナップショット用
        self.purchase_history_db = PurchaseDatabase() # 古物台帳情報の参照用
        self.store_db = StoreDatabase()
        
        from database.receipt_db import ReceiptDatabase
        self.receipt_db = ReceiptDatabase()
        self.inventory_widget = inventory_widget
        self.inventory_columns = self._resolve_inventory_columns()
        self.purchase_columns: List[str] = list(self.inventory_columns)
        self.purchase_records: List[Dict[str, Any]] = []
        self.sales_records: List[Dict[str, Any]] = []
        self.setup_ui()
        self.load_products()
        self.restore_latest_purchase_snapshot()
        self.load_purchase_data(self.purchase_records)
        self.load_sales_data()

        # テーブルの列幅を復元
        restore_table_header_state(self.table, "ProductWidget/ProductTableState")
        # purchase_tableは列幅のみを復元（リサイズモードは常にInteractive）
        restore_table_header_state(self.sales_table, "ProductWidget/SalesTableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.table, "ProductWidget/ProductTableState")
        save_table_column_widths(self.purchase_table, "ProductWidget/PurchaseTableColumnWidths")
        save_table_header_state(self.sales_table, "ProductWidget/SalesTableState")

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
                "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "コメント",
                "発送方法", "仕入先", "コンディション説明"
            ]
        
        # コンディション説明の後に挿入するカラム（順序重要）
        insert_after_condition_note = [
            "ステータス",
            "ステータス理由",
            "レシート画像",
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
            # 古物台帳関連列（新規追加）
            "品目", "品名", "氏名(個人)", "本人確認書類", "確認番号", "確認日", "確認者", "台帳登録済"
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

    # --- 商品タブ ---
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

    # --- 仕入DBタブ ---
    def setup_purchase_tab(self):
        layout = QVBoxLayout(self.purchase_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 検索エリア
        search_group = QGroupBox("検索")
        search_layout = QGridLayout()
        
        # 日付検索
        search_layout.addWidget(QLabel("日付:"), 0, 0)
        self.purchase_search_date = QLineEdit()
        self.purchase_search_date.setPlaceholderText("yyyy-mm-dd または yyyy/mm/dd")
        search_layout.addWidget(self.purchase_search_date, 0, 1)
        
        # SKU検索
        search_layout.addWidget(QLabel("SKU:"), 0, 2)
        self.purchase_search_sku = QLineEdit()
        self.purchase_search_sku.setPlaceholderText("SKUで検索")
        search_layout.addWidget(self.purchase_search_sku, 0, 3)
        
        # ASIN検索
        search_layout.addWidget(QLabel("ASIN:"), 0, 4)
        self.purchase_search_asin = QLineEdit()
        self.purchase_search_asin.setPlaceholderText("ASINで検索")
        search_layout.addWidget(self.purchase_search_asin, 0, 5)

        # JAN検索
        search_layout.addWidget(QLabel("JAN:"), 0, 6)
        self.purchase_search_jan = QLineEdit()
        self.purchase_search_jan.setPlaceholderText("JANで検索")
        search_layout.addWidget(self.purchase_search_jan, 0, 7)
        
        # ステータスフィルタ
        search_layout.addWidget(QLabel("ステータス:"), 1, 0)
        self.purchase_status_filter = QComboBox()
        self.purchase_status_filter.addItem("すべて", "")
        self.purchase_status_filter.addItem("出品可能", "ready")
        self.purchase_status_filter.addItem("破損", "damaged")
        self.purchase_status_filter.addItem("登録不可", "unlistable")
        self.purchase_status_filter.addItem("保管中", "storage")
        self.purchase_status_filter.addItem("次回出品予定", "pending")
        self.purchase_status_filter.currentIndexChanged.connect(self.filter_purchase_records)
        search_layout.addWidget(self.purchase_status_filter, 1, 1)
        
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

        # 仕入DB保存ボタン（手動変更を含めて確実にスナップショット保存）
        self.save_purchase_button = QPushButton("仕入DB保存")
        self.save_purchase_button.setToolTip("現在の仕入DBの内容（テーブル上の変更を含む）をスナップショットとして保存します")
        self.save_purchase_button.clicked.connect(self.save_purchase_from_table)
        controls_layout.addWidget(self.save_purchase_button)

        self.purchase_count_label = QLabel("保存件数: 0件")
        controls_layout.addWidget(self.purchase_count_label)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # 表示モードを初期化
        self.purchase_view_mode = "all"

        # 仕入DBテーブル
        self.purchase_table = DraggableTableWidget()  # ドラッグ対応テーブルに変更
        self.purchase_table.setAlternatingRowColors(True)
        self.purchase_table.setSelectionBehavior(QTableWidget.SelectRows)
        # 編集トリガーを設定（ダブルクリック、選択＋クリック、F2キーで編集可能）
        # ただし、ItemIsEditableフラグが設定されているセルのみ編集可能
        self.purchase_table.setEditTriggers(
            QTableWidget.DoubleClicked | 
            QTableWidget.SelectedClicked | 
            QTableWidget.EditKeyPressed
        )
        
        # ソート機能を有効化
        self.purchase_table.setSortingEnabled(True)
        
        # カスタムコンテキストメニューを有効化
        self.purchase_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.purchase_table.customContextMenuRequested.connect(self._show_purchase_context_menu)
        # セルクリック時の処理を追加（レシート画像をクリックしたときに画像を表示）
        self.purchase_table.cellClicked.connect(self.on_purchase_table_cell_clicked)
        self.purchase_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        
        layout.addWidget(self.purchase_table)

    # --- 販売DBタブ ---
    def setup_sales_tab(self):
        layout = QVBoxLayout(self.sales_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        controls_layout = QHBoxLayout()
        self.reload_sales_button = QPushButton("再読み込み")
        self.reload_sales_button.clicked.connect(self.load_sales_data)
        controls_layout.addWidget(self.reload_sales_button)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        self.sales_table = QTableWidget()
        self.sales_table.setColumnCount(5)
        self.sales_table.setHorizontalHeaderLabels(["販売日", "商品名", "販売価格", "手数料", "利益"])
        layout.addWidget(self.sales_table)

    def get_all_purchase_records(self) -> List[Dict[str, Any]]:
        """現在のすべての仕入レコードを返す"""
        return getattr(self, 'purchase_all_records', [])

    def batch_update_store_codes_from_master(self):
        """
        仕入DBの「仕入先」カラムを店舗マスタの新店舗コードに置き換えるバッチ処理

        - 現在の仕入DBレコード（purchase_all_records）を対象
        - 各レコードの「仕入先」または「店舗コード」から店舗マスタを参照
        - 店舗マスタの store_code が取得できた場合、その値で「仕入先」を上書き
        - テーブル表示と内部キャッシュ（purchase_all_records）を同期
        """
        if not hasattr(self, "purchase_all_records") or not self.purchase_all_records:
            QMessageBox.information(self, "情報", "仕入DBにデータがありません。")
            return

        reply = QMessageBox.question(
            self,
            "確認",
            "仕入DBの「仕入先」カラムを店舗マスタの新店舗コードで置き換えますか？\n"
            "（対応する店舗が見つかった行のみ変更されます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        updated = 0
        skipped = 0

        row_count = self.purchase_table.rowCount()

        for row_idx in range(row_count):
            # テーブルの並び順と内部リストの順序はソート操作でズレる可能性があるため、
            # 行インデックスではなくSKUをキーに該当レコードを探す
            record = None
            try:
                sku_item = self.purchase_table.item(row_idx, self.purchase_columns.index("SKU")) if "SKU" in self.purchase_columns else None
            except ValueError:
                sku_item = None

            sku_key = sku_item.text().strip() if sku_item else ""

            if sku_key and hasattr(self, "purchase_all_records"):
                for r in self.purchase_all_records:
                    r_sku = (r.get("SKU") or r.get("sku") or "").strip()
                    if r_sku == sku_key:
                        record = r
                        break

            # SKUで見つからなかった場合はフォールバックとしてインデックスを使用
            if record is None:
                try:
                    record = self.purchase_all_records[row_idx]
                except (AttributeError, IndexError):
                    skipped += 1
                    continue

            # 既存のコード（旧仕入先コード or 旧店舗コード）を取得
            raw_code = (
                record.get("仕入先")
                or record.get("店舗コード")
                or record.get("store_code")
                or ""
            )
            raw_code = str(raw_code).strip()
            if not raw_code:
                skipped += 1
                continue

            # 余分な店舗名などが含まれている場合は、空白の前までをコードとみなす
            if " " in raw_code:
                raw_code = raw_code.split(" ")[0]

            # 店舗マスタから店舗情報を取得（store_code優先、互換性のため仕入れ先コードも許容）
            try:
                store = self.store_db.get_store_by_code(raw_code)
            except Exception:
                store = None

            if not store:
                skipped += 1
                continue

            new_store_code = (store.get("store_code") or "").strip()
            if not new_store_code:
                skipped += 1
                continue

            # 既に同じコードならスキップ
            if new_store_code == record.get("仕入先"):
                skipped += 1
                continue

            # 内部レコードを更新
            record["仕入先"] = new_store_code
            record["store_code"] = new_store_code  # 補助的に保持

            # テーブルセル（「仕入先」列）を更新
            if "仕入先" in self.purchase_columns:
                col_idx = self.purchase_columns.index("仕入先")
                item = self.purchase_table.item(row_idx, col_idx)
                if not item:
                    item = QTableWidgetItem()
                    self.purchase_table.setItem(row_idx, col_idx, item)
                item.setText(new_store_code)

            updated += 1

        # マスターキャッシュも更新（フィルタ時の整合性を保つ）
        try:
            self.purchase_all_records_master = copy.deepcopy(self.purchase_all_records)
        except Exception:
            pass

        # スナップショットとして保存（次回起動時も新店舗コードが反映されるようにする）
        try:
            self.save_purchase_snapshot()
        except Exception as e:
            print(f"店舗コードバッチ後のスナップショット保存エラー: {e}")

        # 結果をラベルとメッセージで表示
        if hasattr(self, "purchase_count_label"):
            self.purchase_count_label.setText(f"保存件数: {len(self.purchase_all_records)}件（コード更新 {updated}件）")

        QMessageBox.information(
            self,
            "完了",
            f"店舗コードバッチ更新が完了しました。\n\n"
            f"更新: {updated}件\n"
            f"スキップ: {skipped}件"
        )

    def save_purchase_from_table(self):
        """
        仕入DBテーブルの現在の状態を内部レコードに反映してスナップショット保存する

        - 手動編集したセルの内容も含めて保存したい場合に使用
        - SKU列をキーに purchase_all_records / master / purchase_records を更新
        """
        if not hasattr(self, "purchase_all_records") or not self.purchase_all_records:
            QMessageBox.information(self, "情報", "保存する仕入DBデータがありません。")
            return

        # SKU列のインデックスを取得
        sku_col_idx = None
        if "SKU" in self.purchase_columns:
            sku_col_idx = self.purchase_columns.index("SKU")

        if sku_col_idx is None:
            QMessageBox.warning(self, "エラー", "SKU列が見つからないため、保存できません。")
            return

        row_count = self.purchase_table.rowCount()
        col_count = self.purchase_table.columnCount()

        # SKUをキーに全レコードを更新
        for row in range(row_count):
            sku_item = self.purchase_table.item(row, sku_col_idx)
            if not sku_item:
                continue
            sku_val = (sku_item.text() or "").strip()
            if not sku_val:
                continue

            # テーブルの1行分の値を辞書にまとめる
            row_data: Dict[str, Any] = {}
            for col in range(col_count):
                header = self.purchase_columns[col] if col < len(self.purchase_columns) else None
                if not header:
                    continue
                cell_item = self.purchase_table.item(row, col)
                value = cell_item.text() if cell_item else ""
                row_data[header] = value

            # 対象リストをすべて更新
            for lst_name in ["purchase_all_records", "purchase_all_records_master", "purchase_records"]:
                lst = getattr(self, lst_name, None)
                if not lst:
                    continue
                for rec in lst:
                    rec_sku = (rec.get("SKU") or rec.get("sku") or "").strip()
                    if rec_sku == sku_val:
                        # 既存キーを維持しつつ、テーブル側の値で上書き
                        for key, val in row_data.items():
                            rec[key] = val
                        break

        # スナップショット保存
        try:
            self.save_purchase_snapshot()
            QMessageBox.information(self, "保存完了", "仕入DBの現在の内容を保存しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"仕入DBの保存に失敗しました:\n{e}")

    # ===== 画像管理タブとの連携用ユーティリティ =====

    def find_purchase_candidates_by_datetime(
        self,
        base_dt: datetime,
        days_window: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        指定した日時に近い仕入レコード候補を返す

        - 画像の撮影日時から「±N日以内」の仕入データを探すために使用
        - 仕入日カラムは「仕入れ日」または「purchase_date」を想定
        """
        if not hasattr(self, "purchase_all_records") or not self.purchase_all_records:
            return []

        base_date: date = base_dt.date()
        candidates: List[Dict[str, Any]] = []

        for record in self.purchase_all_records:
            raw_date = str(
                record.get("仕入れ日")
                or record.get("purchase_date")
                or ""
            ).strip()
            if not raw_date:
                continue

            norm = self._normalize_date_for_search(raw_date)
            if not norm:
                continue

            try:
                y, m, d = [int(x) for x in norm.split("-")[:3]]
                rec_date = date(y, m, d)
            except Exception:
                continue

            diff_days = abs((rec_date - base_date).days)
            if diff_days <= days_window:
                rec_copy = dict(record)
                rec_copy["_date_diff"] = diff_days
                candidates.append(rec_copy)

        # 日差 → 仕入日 → SKU の順でソート
        def _sort_key(r: Dict[str, Any]):
            return (
                r.get("_date_diff", 9999),
                str(r.get("仕入れ日") or r.get("purchase_date") or ""),
                str(r.get("SKU") or r.get("sku") or ""),
            )

        candidates.sort(key=_sort_key)
        return candidates

    def update_image_paths_for_jan(
        self,
        jan: str,
        image_paths: List[str],
        all_records: List[Dict[str, Any]],
        skip_existing: bool = True,
    ) -> Tuple[bool, int, Optional[Dict[str, Any]]]:
        """
        指定JANに対応する仕入レコードへ画像パスを割り当てる

        Args:
            jan: 対象とするJANコード
            image_paths: 割り当てたい画像パスのリスト
            all_records: 現在の全仕入レコード（purchase_all_records 相当）
            skip_existing: 既に画像列が埋まっている場合はスキップするかどうか

        Returns:
            (success, added_count, record_snapshot)
        """
        if not jan or not image_paths or not all_records:
            return False, 0, None

        jan_norm = str(jan).strip().upper()

        # 対象レコードを探す（最初に見つかった1件を対象とする）
        target_record: Optional[Dict[str, Any]] = None
        for record in all_records:
            record_jan = str(
                record.get("JAN") or record.get("jan") or ""
            ).strip().upper()
            if record_jan == jan_norm:
                target_record = record
                break

        if target_record is None:
            return False, 0, None

        # 画像列名候補（仕入DB側の列名）
        image_columns = [f"画像{i}" for i in range(1, 7)]

        added_count = 0

        # 既存の画像パスを取得（重複登録を避ける）
        existing_paths = set()
        for col in image_columns:
            val = str(target_record.get(col) or "").strip()
            if val:
                existing_paths.add(val)

        for image_path in image_paths:
            if not image_path:
                continue
            image_path = str(image_path)

            if image_path in existing_paths:
                continue

            # 空いている列を探す
            empty_col_name: Optional[str] = None
            for col in image_columns:
                current_val = str(target_record.get(col) or "").strip()
                if not current_val:
                    empty_col_name = col
                    break

            if empty_col_name is None:
                if skip_existing:
                    # すべて埋まっている場合は追加しない
                    continue
                # skip_existing=False の場合は最後の列を上書き
                empty_col_name = image_columns[-1]

            target_record[empty_col_name] = image_path
            existing_paths.add(image_path)
            added_count += 1

        if added_count == 0:
            return True, 0, None

        # purchase_all_records にも変更を反映（同じオブジェクトを指している前提）
        if hasattr(self, "purchase_all_records") and self.purchase_all_records:
            for idx, rec in enumerate(self.purchase_all_records):
                sku1 = rec.get("SKU") or rec.get("sku")
                sku2 = target_record.get("SKU") or target_record.get("sku")
                if sku1 and sku2 and str(sku1) == str(sku2):
                    self.purchase_all_records[idx] = target_record
                    break

        # テーブルを再描画
        self.purchase_records = list(self.purchase_all_records)
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()

        # スナップショット用にコピーを返す
        record_snapshot = dict(target_record)
        return True, added_count, record_snapshot

    def load_products(self):
        """商品データを読み込み"""
        try:
            products = self.db.list_all()
            self.table.setRowCount(len(products))
            for i, product in enumerate(products):
                self.table.setItem(i, 0, QTableWidgetItem(product.get("sku") or ""))
                self.table.setItem(i, 1, QTableWidgetItem(product.get("product_name") or ""))
                self.table.setItem(i, 2, QTableWidgetItem(product.get("jan") or ""))
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
        """販売データを読み込み（仮実装）"""
        pass

    # --- 仕入DB関連 ---
    def load_purchase_data(self, records: List[Dict[str, Any]]):
        """仕入DBデータを読み込み"""
        # 起動時はスナップショットから復元されるため、DB側の最新情報（ステータス/理由など）をマージしてから表示する
        try:
            records = self._augment_purchase_records(records or [])
        except Exception as e:
            print(f"仕入DBデータのaugmentエラー: {e}")
        # マスターを保持しておき、フィルタ時はそこから再計算する
        self.purchase_all_records_master = copy.deepcopy(records)
        self.purchase_all_records = copy.deepcopy(records)
        self.purchase_records = copy.deepcopy(records)
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()

    def save_purchase_snapshot(self):
        """現在の仕入データをスナップショットとして保存"""
        if not hasattr(self, 'purchase_all_records') or not self.purchase_all_records:
            return
        try:
            snapshot_name = f"Snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.purchase_db.save_snapshot(snapshot_name, self.purchase_all_records)
        except Exception as e:
            print(f"スナップショット保存エラー: {e}")

    def restore_latest_purchase_snapshot(self):
        """最新のスナップショットを復元"""
        try:
            snapshots = self.purchase_db.list_snapshots()
            if snapshots:
                latest_id = snapshots[0]["id"]
                snapshot = self.purchase_db.get_snapshot(latest_id)
                if snapshot:
                    self.purchase_all_records = snapshot["data"]
                    self.purchase_records = list(self.purchase_all_records)
                    return
        except Exception as e:
            print(f"スナップショット復元エラー: {e}")
        
        self.purchase_all_records = []
        self.purchase_records = []

    def on_import_inventory(self):
        """仕入管理タブからデータを取り込み"""
        records = self._collect_inventory_records()
        if records:
            if hasattr(self, 'purchase_all_records') and self.purchase_all_records:
                reply = QMessageBox.question(
                    self, "確認", 
                    "既存のデータがあります。追加しますか？\n（Noを選ぶと既存データはクリアされます）",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
                )
                if reply == QMessageBox.Cancel:
                    return
                if reply == QMessageBox.No:
                    self.purchase_all_records = []
            else:
                self.purchase_all_records = []
            
            existing_skus = {r.get("SKU") or r.get("sku") for r in self.purchase_all_records}
            new_count = 0
            for r in records:
                sku = r.get("SKU") or r.get("sku")
                if sku and sku not in existing_skus:
                    self.purchase_all_records.append(r)
                    existing_skus.add(sku)
                    new_count += 1
                elif not sku:
                    self.purchase_all_records.append(r)
                    new_count += 1
            
            self.purchase_records = list(self.purchase_all_records)
            self.populate_purchase_table(self.purchase_records)
            self.update_purchase_count_label()
            self.save_purchase_snapshot()
            
            QMessageBox.information(self, "完了", f"{new_count}件のデータを取り込みました。")

    def on_delete_purchase_row(self):
        """選択行を削除"""
        rows = sorted(set(index.row() for index in self.purchase_table.selectedIndexes()), reverse=True)
        if not rows:
            QMessageBox.warning(self, "選択なし", "削除する行を選択してください。")
            return
            
        if QMessageBox.question(self, "確認", f"{len(rows)}件のデータを削除しますか？") != QMessageBox.Yes:
            return

        for row in rows:
            if 0 <= row < len(self.purchase_records):
                del self.purchase_records[row]
        
        self.purchase_all_records = list(self.purchase_records)
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
        self.save_purchase_snapshot()

    def on_delete_all_purchase(self):
        """全行削除"""
        if not self.purchase_records:
            return
            
        if QMessageBox.question(self, "確認", "表示中の全データを削除しますか？") != QMessageBox.Yes:
            return
            
        self.purchase_records = []
        self.purchase_all_records = []
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
        self.save_purchase_snapshot()

    def filter_purchase_records(self):
        """検索条件でフィルタリング"""
        date_query = self.purchase_search_date.text().strip()
        sku_query = self.purchase_search_sku.text().strip().lower()
        asin_query = self.purchase_search_asin.text().strip().lower()
        jan_query = self.purchase_search_jan.text().strip().lower()
        status_filter = self.purchase_status_filter.currentData()
        # マスターがなければ空で初期化
        if not hasattr(self, 'purchase_all_records_master') or self.purchase_all_records_master is None:
            self.purchase_all_records_master = []
        if not hasattr(self, 'purchase_all_records') or self.purchase_all_records is None:
            self.purchase_all_records = []

        # マスターから都度フィルタ（前回の結果に依存しない）
        source_records = self.purchase_all_records_master if self.purchase_all_records_master else self.purchase_all_records
        filtered_records = copy.deepcopy(source_records)

        # 日付フィルタ
        if date_query:
            filtered_records = [
                r for r in filtered_records
                if self._date_matches(str(r.get("仕入れ日") or ""), date_query)
            ]

        # SKUフィルタ
        if sku_query:
            filtered_records = [
                r for r in filtered_records
                if sku_query in str(r.get("SKU") or r.get("sku") or "").lower()
            ]

        # ASINフィルタ
        if asin_query:
            filtered_records = [
                r for r in filtered_records
                if asin_query in str(r.get("ASIN") or r.get("asin") or "").lower()
            ]

        # JANフィルタ
        if jan_query:
            filtered_records = [
                r for r in filtered_records
                if jan_query in str(r.get("JAN") or r.get("jan") or "").lower()
            ]

        # ステータスフィルタ
        if status_filter:
            sf = str(status_filter).lower()
            filtered_records = [
                r for r in filtered_records
                if str(r.get("ステータス") or r.get("status") or "ready").lower() == sf
            ]

        # 結果を反映
        self.purchase_records = filtered_records
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
    
    def clear_purchase_search(self):
        """検索条件をクリアして全件表示"""
        self.purchase_search_date.clear()
        self.purchase_search_sku.clear()
        self.purchase_search_asin.clear()
        self.purchase_search_jan.clear()
        self.purchase_status_filter.setCurrentIndex(0)  # "すべて"を選択
        self.purchase_records = list(self.purchase_all_records) if hasattr(self, 'purchase_all_records') else []
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
    
    def toggle_view_mode(self, mode: str):
        """表示モードを切り替え"""
        # 既に選択されているボタンを再度クリックした場合は何もしない
        if hasattr(self, 'purchase_view_mode') and self.purchase_view_mode == mode:
            # 同じボタンを再度クリックした場合は、ALLに戻す
            if mode != "all":
                mode = "all"
            else:
                return  # 既にALLが選択されている場合は何もしない
        
        # ボタンの状態を更新
        self.view_all_button.setChecked(mode == "all")
        self.view_status_button.setChecked(mode == "status")
        self.view_image_button.setChecked(mode == "image")
        self.view_ledger_button.setChecked(mode == "ledger")
        
        self.purchase_view_mode = mode
        
        # 列の表示/非表示を更新
        self._update_column_visibility()
    
    def _update_column_visibility(self):
        """列の表示/非表示を更新"""
        if not hasattr(self, 'purchase_columns'):
            return
        
        # 「仕入れ個数」列のインデックスを取得
        quantity_col_idx = None
        for i, col_name in enumerate(self.purchase_columns):
            if col_name == "仕入れ個数":
                quantity_col_idx = i
                break
        
        if quantity_col_idx is None:
            return
        
        # 表示する列の範囲を定義
        if self.purchase_view_mode == "all":
            # 全列表示
            visible_ranges = [(quantity_col_idx + 1, len(self.purchase_columns))]
        elif self.purchase_view_mode == "status":
            # ステータス・ステータス理由のみ
            status_start = None
            status_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "ステータス":
                    status_start = i
                if col_name == "ステータス理由":
                    status_end = i + 1
                    break
            if status_start is not None and status_end is not None:
                visible_ranges = [(status_start, status_end)]
            else:
                visible_ranges = []
        elif self.purchase_view_mode == "image":
            # レシート画像から画像URL6まで
            image_start = None
            image_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "レシート画像":
                    image_start = i
                if col_name == "画像URL6":
                    image_end = i + 1
                    break
            if image_start is not None and image_end is not None:
                visible_ranges = [(image_start, image_end)]
            else:
                visible_ranges = []
        elif self.purchase_view_mode == "ledger":
            # 品目から台帳登録済まで
            ledger_start = None
            ledger_end = None
            for i, col_name in enumerate(self.purchase_columns):
                if col_name == "品目":
                    ledger_start = i
                if col_name == "台帳登録済":
                    ledger_end = i + 1
                    break
            if ledger_start is not None and ledger_end is not None:
                visible_ranges = [(ledger_start, ledger_end)]
            else:
                visible_ranges = []
        else:
            visible_ranges = []
        
        # 列の表示/非表示を設定
        for col_idx in range(len(self.purchase_columns)):
            # 「仕入れ個数」より左の列は常に表示
            if col_idx <= quantity_col_idx:
                self.purchase_table.setColumnHidden(col_idx, False)
            else:
                # 「仕入れ個数」より右の列は、表示範囲内かどうかで判定
                is_visible = False
                if self.purchase_view_mode == "all":
                    is_visible = True
                else:
                    for start, end in visible_ranges:
                        if start <= col_idx < end:
                            is_visible = True
                            break
                self.purchase_table.setColumnHidden(col_idx, not is_visible)
    
    def update_purchase_count_label(self):
        """保存件数ラベルを更新"""
        if not hasattr(self, 'purchase_all_records'):
            self.purchase_all_records = []
            
        total_count = len(self.purchase_all_records)
        filtered_count = len(self.purchase_records)
        
        if total_count == filtered_count:
            self.purchase_count_label.setText(f"保存件数: {total_count}件（スナップショット: 最大10件まで）")
        else:
            self.purchase_count_label.setText(f"表示: {filtered_count}件 / 全件: {total_count}件（スナップショット: 最大10件まで）")
    
    def _normalize_date_for_search(self, date_str: str) -> Optional[str]:
        """検索用に日付を正規化（yyyy-mm-dd形式）"""
        if not date_str:
            return None
        # 区切り文字と日本語表記を統一
        date_str = (
            str(date_str)
            .replace("/", "-")
            .replace(".", "-")
            .replace("年", "-")
            .replace("月", "-")
            .replace("日", "")
        )
        parts = date_str.split("-")
        if len(parts) >= 3:
            try:
                year = int(parts[0])
                month = int(parts[1])
                # 3つ目の要素に「日付＋時刻」が入っているケースに対応（例: '29 15:56'）
                day_part = parts[2]
                import re as _re
                m = _re.match(r"\s*(\d{1,2})", str(day_part))
                if not m:
                    return date_str
                day = int(m.group(1))
                return f"{year:04d}-{month:02d}-{day:02d}"
            except ValueError:
                pass
        return date_str
    
    def _date_matches(self, record_date: str, search_date: str) -> bool:
        """日付が一致するかチェック（部分一致対応）"""
        if not record_date or not search_date:
            return False
        normalized_record = self._normalize_date_for_search(str(record_date))
        if not normalized_record:
            return False
        return search_date in normalized_record or normalized_record.startswith(search_date)

    def _collect_inventory_records(self) -> Optional[List[Dict[str, Any]]]:
        if not self.inventory_widget:
            QMessageBox.warning(self, "取り込み不可", "仕入管理タブへの参照がありません。")
            return None
        try:
            df = None
            if hasattr(self.inventory_widget, "get_table_data"):
                df = self.inventory_widget.get_table_data()
            if df is None:
                df = getattr(self.inventory_widget, "inventory_data", None)
            if df is None or len(df) == 0:
                QMessageBox.warning(self, "データなし", "仕入管理のデータが空です。")
                return None
        except Exception as e:
            QMessageBox.critical(self, "取り込みエラー", f"仕入データ取得に失敗しました:\n{e}")
            return None

        try:
            df = df.fillna("")
        except Exception:
            pass
        try:
            records = df.to_dict(orient="records")
        except Exception as e:
            QMessageBox.critical(self, "変換エラー", f"データ変換に失敗しました:\n{e}")
            return None
        return self._augment_purchase_records(records)

    def _augment_purchase_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """保証・レシート情報・古物台帳情報を付与"""
        augmented: List[Dict[str, Any]] = []
        for record in records:
            row = dict(record)
            sku = row.get("SKU") or row.get("sku")
            
            # 画像URLをrecordから取得（既に設定されている場合はスキップ）
            for i in range(1, 7):
                image_url_key = f"image_url_{i}"
                image_url_col = f"画像URL{i}"
                if image_url_col not in row or not row.get(image_url_col):
                    image_url = record.get(image_url_key) or record.get(f"画像URL{i}")
                    if image_url:
                        row[image_url_col] = image_url
            comment_warranty = self._infer_warranty_from_comment(row)
            if comment_warranty:
                # コメントから取得した保証期間は保証最終日として扱う
                row["保証最終日"] = comment_warranty

            if sku:
                try:
                    product = self.db.get_by_sku(sku)
                except Exception:
                    product = None
                if product:
                    # 保証期間（日数）を取得
                    warranty_period_days = product.get("warranty_period_days")
                    if warranty_period_days is not None and "保証期間" not in row:
                        row["保証期間"] = warranty_period_days
                    
                    # 保証最終日を取得
                    warranty_until = product.get("warranty_until")
                    if warranty_until and "保証最終日" not in row:
                        row["保証最終日"] = warranty_until
                    
                    if "レシート画像" not in row and product.get("receipt_id") is not None:
                        row["レシート画像"] = product.get("receipt_id")
                    for i in range(1, 7):
                        image_key = f"image_{i}"
                        image_col = f"画像{i}"
                        if image_col not in row or not row.get(image_col):
                            image_path = product.get(image_key)
                            if image_path:
                                row[image_col] = image_path
                        # 画像URLを取得
                        image_url_key = f"image_url_{i}"
                        image_url_col = f"画像URL{i}"
                        if image_url_col not in row or not row.get(image_url_col):
                            image_url = product.get(image_url_key)
                            if image_url:
                                row[image_url_col] = image_url
                # 保証書情報の取得
                try:
                    warranties = self.warranty_db.list_by_sku(sku)
                except Exception:
                    warranties = []
                
                if warranties:
                    # 最新の保証書を取得
                    warranty = warranties[0]
                    # 保証書画像（ファイル名、拡張子なし）
                    warranty_file_path = warranty.get('file_path', '')
                    if warranty_file_path:
                        from pathlib import Path
                        warranty_image_name = Path(warranty_file_path).stem
                        if "保証書画像" not in row:
                            row["保証書画像"] = warranty_image_name
                    
                    # 保証書ID（後方互換性のため保持、ただし保証書画像が設定されていない場合のみ）
                    warranty_id = warranty.get('id')
                    if warranty_id is not None:
                        # 旧カラム名「保証書ID」も設定（後方互換性）
                        if "保証書ID" not in row:
                            row["保証書ID"] = warranty_id
                else:
                    # 保証書DBにない場合、既存の「保証書ID」から保証書画像を取得を試みる
                    if "保証書画像" not in row and "保証書ID" in row:
                        warranty_id = row.get("保証書ID")
                        if warranty_id:
                            try:
                                warranty = self.warranty_db.get_warranty(int(warranty_id))
                                if warranty:
                                    warranty_file_path = warranty.get('file_path', '')
                                    if warranty_file_path:
                                        from pathlib import Path
                                        warranty_image_name = Path(warranty_file_path).stem
                                        row["保証書画像"] = warranty_image_name
                            except Exception:
                                pass
                
                # 保証期間と保証最終日をProductDatabaseから取得
                if product:
                    # 保証期間（日数）を取得
                    warranty_period_days = product.get("warranty_period_days")
                    if warranty_period_days is not None and "保証期間" not in row:
                        row["保証期間"] = warranty_period_days
                    
                    # 保証最終日を取得
                    warranty_until = product.get("warranty_until")
                    if warranty_until and "保証最終日" not in row:
                        row["保証最終日"] = warranty_until

                # --- 古物台帳情報の取得（新規追加） ---
                try:
                    purchase_info = self.purchase_history_db.get_by_sku(sku)
                    if purchase_info:
                        ledger_map = {
                            "kobutsu_kind": "品目",
                            "hinmoku": "品目", 
                            "hinmei": "品名",
                            "person_name": "氏名(個人)",
                            "id_type": "本人確認書類",
                            "id_number": "確認番号",
                            "id_checked_on": "確認日",
                            "id_checked_by": "確認者",
                            "ledger_registered": "台帳登録済"
                        }
                        for db_col, disp_col in ledger_map.items():
                            val = purchase_info.get(db_col)
                            if val is not None:
                                if db_col == "ledger_registered":
                                    row[disp_col] = "済" if val else ""
                                else:
                                    row[disp_col] = val
                        
                        # ステータス情報を取得
                        status = purchase_info.get("status", "ready")
                        status_reason = purchase_info.get("status_reason", "")
                        status_set_at = purchase_info.get("status_set_at", "")
                        row["ステータス"] = status
                        row["status"] = status
                        if status_reason:
                            row["ステータス理由"] = status_reason
                            row["status_reason"] = status_reason
                        if status_set_at:
                            row["status_set_at"] = status_set_at
                except Exception as e:
                    print(f"古物台帳情報取得エラー(SKU={sku}): {e}")

            augmented.append(row)
        return augmented

    def populate_purchase_table(self, records: List[Dict[str, Any]]):
        """仕入DBテーブルにレコードを反映"""
        from pathlib import Path
        records = records or []
        
        base_columns = list(self.inventory_columns)
        if not base_columns:
            base_columns = self._resolve_inventory_columns()
        columns = list(base_columns)
        seen = set(col.upper() for col in columns)
        
        # レコードから追加の列を取得（既にcolumnsに含まれているものは除外）
        for record in records:
            for key in record.keys():
                upper_key = key.upper()
                if upper_key not in seen:
                    seen.add(upper_key)
                    columns.append(key)
        self.purchase_columns = columns

        # テーブル内容をクリアし、更新中はソート/シグナルを止める（穴あき防止）
        self.purchase_table.blockSignals(True)
        self.purchase_table.setSortingEnabled(False)
        self.purchase_table.clearContents()
        self.purchase_table.setRowCount(len(records))
        self.purchase_table.setColumnCount(len(columns))
        # 表示ラベルだけ「仕入先」→「店舗コード」に置き換え
        display_columns = list(columns)
        try:
            idx = display_columns.index("仕入先")
            display_columns[idx] = "店舗コード"
        except ValueError:
            pass
        self.purchase_table.setHorizontalHeaderLabels(display_columns)
        
        # 列幅を変更可能にする設定（データ設定前に設定）
        header = self.purchase_table.horizontalHeader()
        for col_idx in range(len(columns)):
            header.setSectionResizeMode(col_idx, QHeaderView.Interactive)

        for row, record in enumerate(records):
            for col, header in enumerate(columns):
                value = self._get_record_value(record, [header])
                if value is None:
                    value = ""
                
                if header == "商品名":
                    full_text = "" if value is None else str(value)
                    display_text = self._truncate_text(full_text, PRODUCT_NAME_DISPLAY_LIMIT)
                    item = QTableWidgetItem(display_text)
                    if full_text:
                        item.setToolTip(full_text)
                    item.setData(Qt.UserRole, full_text)
                elif header == "レシート画像":
                    receipt_image_str = "" if value is None else str(value)
                    item = QTableWidgetItem(receipt_image_str)
                    if receipt_image_str:
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                        # レコードにファイルパス情報が保存されている場合は優先的に使用
                        file_path = record.get('レシート画像パス') or record.get('receipt_image_path')
                        if file_path:
                            # ファイルパスがレコードに保存されている場合
                            file_path_obj = Path(file_path)
                            if file_path_obj.exists():
                                item.setToolTip(f"クリックで画像を開く\n{file_path}")
                                item.setData(Qt.UserRole, str(file_path_obj.resolve()))
                            else:
                                # ファイルが存在しない場合は、file_pathをそのまま保存（後で検索できるように）
                                item.setToolTip(f"レシート画像: {receipt_image_str}\n（ファイルが見つかりません: {file_path}）")
                                item.setData(Qt.UserRole, file_path)
                        else:
                            # レコードにファイルパスがない場合は、レシートDBから検索
                            receipt_info = self.receipt_db.find_by_file_name(receipt_image_str)
                            if receipt_info:
                                # original_file_pathを優先、なければfile_path
                                file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path')
                                if file_path:
                                    # ファイルが存在するか確認
                                    file_path_obj = Path(file_path)
                                    if file_path_obj.exists():
                                        item.setToolTip(f"クリックで画像を開く\n{file_path}")
                                        item.setData(Qt.UserRole, str(file_path_obj.resolve()))
                                    else:
                                        # ファイルが存在しない場合は、file_pathをそのまま保存（後で検索できるように）
                                        item.setToolTip(f"レシート画像: {receipt_image_str}\n（ファイルが見つかりません: {file_path}）")
                                        item.setData(Qt.UserRole, file_path)
                                else:
                                    # デバッグ: レシート情報は見つかったが、file_pathがない
                                    item.setToolTip("レシート画像: " + receipt_image_str + "\n（レシートDBにfile_pathがありません）")
                                    # UserRoleにはreceipt_idを保存して、後で検索できるようにする
                                    item.setData(Qt.UserRole, receipt_image_str)
                            else:
                                # レシートが見つからない場合
                                item.setToolTip("レシート画像: " + receipt_image_str + "\n（レシートDBに見つかりません）")
                                # UserRoleにはファイル名を保存して、後で検索できるようにする
                                item.setData(Qt.UserRole, receipt_image_str)
                        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
                elif header == "保証書画像":
                    warranty_image_str = "" if value is None else str(value)
                    item = QTableWidgetItem(warranty_image_str)
                    if warranty_image_str:
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                        # レシートDBからファイルパスを取得（保証書もレシートDBに保存されている）
                        warranty_file_path = None
                        try:
                            # まずレシートDBから検索（ファイル名で検索）
                            receipt_info = self.receipt_db.find_by_file_name(warranty_image_str)
                            if receipt_info:
                                # original_file_pathを優先、なければfile_path
                                warranty_file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path', '')
                        except Exception:
                            pass
                        
                        # レシートDBで見つからない場合は、保証書DBから検索
                        if not warranty_file_path:
                            try:
                                warranties = self.warranty_db.list_by_sku(record.get('SKU') or record.get('sku') or '')
                                if warranties:
                                    # 最新の保証書を取得
                                    warranty = warranties[0]
                                    warranty_file_path = warranty.get('file_path', '')
                            except Exception:
                                pass
                        
                        if warranty_file_path:
                            file_path_obj = Path(warranty_file_path)
                            if file_path_obj.exists():
                                item.setToolTip(f"クリックで画像を開く\n{warranty_file_path}")
                                item.setData(Qt.UserRole, str(file_path_obj.resolve()))
                            else:
                                item.setToolTip(f"保証書画像: {warranty_image_str}\n（ファイルが見つかりません: {warranty_file_path}）")
                                item.setData(Qt.UserRole, warranty_file_path)
                        else:
                            item.setToolTip("保証書画像: " + warranty_image_str + "\n（ファイルパスが見つかりません）")
                            item.setData(Qt.UserRole, warranty_image_str)
                        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
                elif header and header.startswith("画像") and header[2:].isdigit():
                    image_path = value or ""
                    if image_path:
                        image_name = Path(image_path).name
                        item = QTableWidgetItem(image_name)
                        item.setData(Qt.UserRole, image_path)
                        item.setToolTip(f"クリックで画像を開く\n{image_path}")
                        item.setForeground(Qt.white)  # 青色から白色に変更
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)
                    else:
                        item = QTableWidgetItem("")
                elif header and header.startswith("画像URL") and header[6:].isdigit():
                    # 画像URL列の処理
                    image_url = value or ""
                    if image_url:
                        item = QTableWidgetItem(str(image_url))
                        item.setToolTip(f"画像URL: {image_url}")
                    else:
                        item = QTableWidgetItem("")
                elif header == "想定利益率" or header == "想定ROI":
                    # 想定利益率・想定ROI列の処理：空欄の場合は再計算
                    value_str = str(value) if value else ""
                    value_float = None
                    try:
                        if value_str:
                            value_float = float(value_str)
                    except (ValueError, TypeError):
                        value_float = None
                    
                    # 空欄または0の場合は再計算
                    if value_float is None or value_float == 0:
                        # 再計算に必要な値を取得
                        purchase_price = None
                        planned_price = None
                        expected_profit = None
                        
                        # 仕入れ価格を取得
                        purchase_price_key = None
                        for key in ["仕入れ価格", "仕入価格", "purchase_price", "cost"]:
                            if key in record:
                                purchase_price_key = key
                                break
                        if purchase_price_key:
                            try:
                                purchase_price = float(record[purchase_price_key]) if record[purchase_price_key] else 0
                            except (ValueError, TypeError):
                                purchase_price = 0
                        
                        # 販売予定価格を取得
                        planned_price_key = None
                        for key in ["販売予定価格", "planned_price", "price"]:
                            if key in record:
                                planned_price_key = key
                                break
                        if planned_price_key:
                            try:
                                planned_price = float(record[planned_price_key]) if record[planned_price_key] else 0
                            except (ValueError, TypeError):
                                planned_price = 0
                        
                        # 見込み利益を取得
                        expected_profit_key = None
                        for key in ["見込み利益", "expected_profit", "profit"]:
                            if key in record:
                                expected_profit_key = key
                                break
                        if expected_profit_key:
                            try:
                                expected_profit = float(record[expected_profit_key]) if record[expected_profit_key] else 0
                            except (ValueError, TypeError):
                                expected_profit = 0
                        
                        # 見込み利益が計算されていない場合は計算
                        if expected_profit is None or expected_profit == 0:
                            if planned_price and purchase_price:
                                other_cost = record.get('その他費用') or record.get('other_cost') or 0
                                try:
                                    other_cost = float(other_cost) if other_cost else 0
                                except (ValueError, TypeError):
                                    other_cost = 0
                                expected_profit = planned_price - purchase_price - other_cost
                        
                        # 想定利益率または想定ROIを計算
                        if header == "想定利益率":
                            if planned_price and planned_price > 0 and expected_profit:
                                calculated_value = (expected_profit / planned_price) * 100
                                value_float = round(calculated_value, 2)
                                # レコードにも保存
                                record['想定利益率'] = value_float
                            else:
                                value_float = 0.0
                        elif header == "想定ROI":
                            if purchase_price and purchase_price > 0 and expected_profit:
                                calculated_value = (expected_profit / purchase_price) * 100
                                value_float = round(calculated_value, 2)
                                # レコードにも保存
                                record['想定ROI'] = value_float
                            else:
                                value_float = 0.0
                    
                    # 値を表示
                    if value_float is not None and value_float != 0:
                        item = QTableWidgetItem(f"{value_float:.2f}")
                    else:
                        item = QTableWidgetItem("")
                elif header == "仕入れ日" or header.upper() == "PURCHASE_DATE":
                    # 仕入れ日列の処理：ソート用の値を設定
                    date_str = str(value) if value else ""
                    # ソート用の値を設定（datetimeオブジェクトまたはタイムスタンプ）
                    sort_value = 0.0
                    if date_str:
                        try:
                            # 日付文字列をパース（複数の形式に対応）
                            date_str_clean = date_str.strip()
                            # "2025/12/6 10:16" 形式を想定
                            if " " in date_str_clean:
                                date_part, time_part = date_str_clean.split(" ", 1)
                                date_part = date_part.replace("/", "-")
                                datetime_str = f"{date_part} {time_part}"
                                # "YYYY-MM-DD HH:MM" 形式でパース
                                dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                sort_value = dt.timestamp()
                            else:
                                # 日付のみの場合
                                date_part = date_str_clean.replace("/", "-")
                                dt = datetime.strptime(date_part, "%Y-%m-%d")
                                sort_value = dt.timestamp()
                        except Exception:
                            try:
                                # 別の形式を試す
                                date_part = date_str_clean.replace("/", "-").split(" ")[0]
                                dt = datetime.strptime(date_part, "%Y-%m-%d")
                                sort_value = dt.timestamp()
                            except Exception:
                                # パースに失敗した場合は、0を設定（最古として扱う）
                                sort_value = 0.0
                    # SortableDateItemを使用してソート可能にする
                    item = SortableDateItem(date_str, sort_value)
                elif header == "ステータス":
                    # ステータス列の処理：プルダウンで選択可能
                    status_value = str(value) if value else "ready"
                    status_combo = QComboBox()
                    status_combo.addItem("出品可能", "ready")
                    status_combo.addItem("破損", "damaged")
                    status_combo.addItem("登録不可", "unlistable")
                    status_combo.addItem("保管中", "storage")
                    status_combo.addItem("次回出品予定", "pending")
                    
                    # 現在の値を設定
                    current_index = 0
                    for i in range(status_combo.count()):
                        if status_combo.itemData(i) == status_value:
                            current_index = i
                            break
                    status_combo.setCurrentIndex(current_index)
                    
                    # ステータス変更時の処理
                    def on_status_changed(idx, r=row, rec=record):
                        new_status = status_combo.itemData(idx)
                        rec["ステータス"] = new_status
                        rec["status"] = new_status
                        # ステータス設定日時を更新
                        rec["status_set_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # purchase_all_records / master / purchase_records を更新
                        sku = rec.get("SKU") or rec.get("sku")
                        if sku:
                            for target_list in ["purchase_all_records", "purchase_all_records_master", "purchase_records"]:
                                lst = getattr(self, target_list, None)
                                if lst:
                                    for t_rec in lst:
                                        t_sku = t_rec.get("SKU") or t_rec.get("sku")
                                        if t_sku == sku:
                                            t_rec["ステータス"] = new_status
                                            t_rec["status"] = new_status
                                            t_rec["status_set_at"] = rec["status_set_at"]
                                            break
                        
                        # データベースに保存（ステータス理由も含める）
                        if sku:
                            try:
                                # ステータス理由も取得して保存
                                status_reason = rec.get("ステータス理由") or rec.get("status_reason") or ""
                                purchase_data = {
                                    "sku": sku,
                                    "status": new_status,
                                    "status_reason": status_reason,
                                    "status_set_at": rec["status_set_at"]
                                }
                                self.purchase_history_db.upsert(purchase_data)
                                print(f"ステータス保存成功: SKU={sku}, status={new_status}, status_reason={status_reason}")
                            except Exception as e:
                                import traceback
                                error_msg = f"ステータス保存エラー (SKU={sku}): {e}\n{traceback.format_exc()}"
                                print(error_msg)
                                QMessageBox.warning(
                                    self,
                                    "保存エラー",
                                    f"ステータスの保存に失敗しました。\nSKU: {sku}\nエラー: {str(e)}"
                                )
                        
                        # 行の背景色を更新
                        self._update_row_color_by_status(r, new_status)

                        # ステータスフィルタをリセットして再描画（変更後に行が消えないよう常に全件表示に戻す）
                        if hasattr(self, 'purchase_status_filter'):
                            try:
                                self.purchase_status_filter.blockSignals(True)
                                self.purchase_status_filter.setCurrentIndex(0)  # 「すべて」
                            finally:
                                self.purchase_status_filter.blockSignals(False)

                        # フィルタを再適用（全件表示）してテーブルを再描画
                        self.filter_purchase_records()
                        # 表示モードに応じた列の表示/非表示を確実に更新
                        self._update_column_visibility()

                        # スナップショットも保存（次回起動時にステータスがリセットされないようにする）
                        try:
                            self.save_purchase_snapshot()
                        except Exception as e:
                            print(f"スナップショット保存エラー(ステータス変更): {e}")
                    
                    status_combo.currentIndexChanged.connect(on_status_changed)
                    self.purchase_table.setCellWidget(row, col, status_combo)
                    continue  # セルウィジェットを設定したので、itemは設定しない
                elif header == "ステータス理由":
                    # ステータス理由列の処理：編集可能なテキスト
                    reason_value = str(value) if value else ""
                    item = QTableWidgetItem(reason_value)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    # 編集時の処理は、itemChangedシグナルで処理（後で接続）
                else:
                    item = QTableWidgetItem(str(value))
                
                if header != "ステータス":  # ステータス列はセルウィジェットを設定済み
                    self.purchase_table.setItem(row, col, item)
        
        # すべての行の背景色を設定（ステータスに応じて）
        for row in range(len(records)):
            record = records[row]
            status_value = str(record.get("ステータス") or record.get("status") or "ready")
            self._update_row_color_by_status(row, status_value)

        # 各列をリサイズ可能に設定
        header = self.purchase_table.horizontalHeader()
        for col_idx in range(len(columns)):
            header.setSectionResizeMode(col_idx, QHeaderView.Interactive)
        
        # 列幅のみを復元（リサイズモードは変更しない）
        restore_table_column_widths(self.purchase_table, "ProductWidget/PurchaseTableColumnWidths")
        
        # ステータス理由列の編集時の処理を接続（既存の接続を解除してから接続）
        status_reason_col_idx = None
        sku_col_idx = None
        status_col_idx = None
        for col_idx, col_name in enumerate(columns):
            if col_name == "ステータス理由":
                status_reason_col_idx = col_idx
            if col_name == "SKU":
                sku_col_idx = col_idx
            if col_name == "ステータス":
                status_col_idx = col_idx
        # SKU列が無い場合は安全に終了
        if sku_col_idx is None:
            sku_col_idx = None
        
        if status_reason_col_idx is not None:
            # 既存のitemChangedシグナル接続を解除（重複接続を防ぐ）
            # 注意: disconnect()を引数なしで呼ぶと、接続がない場合にRuntimeWarningが出るが、
            # 動作には影響しないため、例外をキャッチして無視する
            try:
                self.purchase_table.itemChanged.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                # 接続がない場合や切断に失敗した場合はエラーを無視
                pass
            
            # itemChangedシグナルを接続（編集時に自動保存）
            def on_item_changed(item_changed):
                if item_changed.column() == status_reason_col_idx:
                    row = item_changed.row()
                    if row < 0:
                        return

                    new_reason = item_changed.text()

                    # ソート有効時は records[row] が別レコードになるため、テーブル上のSKUで特定する
                    sku_val = None
                    if sku_col_idx is not None:
                        sku_item = self.purchase_table.item(row, sku_col_idx)
                        if sku_item:
                            sku_val = (sku_item.text() or "").strip()
                    if not sku_val:
                        # フォールバック：recordsから取る（ソートしていない前提）
                        if 0 <= row < len(records):
                            sku_val = (records[row].get("SKU") or records[row].get("sku") or "").strip()
                    if not sku_val:
                        return

                    # まず表示用records（この描画に渡ってきたリスト）にも反映（見た目が戻らないように）
                    if 0 <= row < len(records):
                        records[row]["ステータス理由"] = new_reason
                        records[row]["status_reason"] = new_reason

                    # purchase_all_records / master / purchase_records へ反映（再描画・再起動で消えないようにする）
                    for target_list in ["purchase_all_records", "purchase_all_records_master", "purchase_records"]:
                        lst = getattr(self, target_list, None)
                        if not lst:
                            continue
                        for t_rec in lst:
                            t_sku = (t_rec.get("SKU") or t_rec.get("sku") or "")
                            if str(t_sku).strip() == sku_val:
                                t_rec["ステータス理由"] = new_reason
                                t_rec["status_reason"] = new_reason
                                break

                    # 現在のステータスもテーブルから取得（可能なら）
                    current_status = None
                    if status_col_idx is not None:
                        w = self.purchase_table.cellWidget(row, status_col_idx)
                        if isinstance(w, QComboBox):
                            current_status = w.currentData()
                    if not current_status:
                        # フォールバック：マスターから取得
                        current_status = "ready"
                        for lst_name in ["purchase_all_records_master", "purchase_all_records"]:
                            lst = getattr(self, lst_name, None)
                            if not lst:
                                continue
                            for t_rec in lst:
                                t_sku = (t_rec.get("SKU") or t_rec.get("sku") or "")
                                if str(t_sku).strip() == sku_val:
                                    current_status = t_rec.get("ステータス") or t_rec.get("status") or "ready"
                                    break

                    # データベースに保存（ステータスも一緒に保存）
                    try:
                        purchase_data = {
                            "sku": sku_val,
                            "status": current_status,
                            "status_reason": new_reason
                        }
                        self.purchase_history_db.upsert(purchase_data)
                        print(f"ステータス理由保存成功: SKU={sku_val}, status={current_status}, status_reason={new_reason}")
                    except Exception as e:
                        import traceback
                        error_msg = f"ステータス理由保存エラー (SKU={sku_val}): {e}\n{traceback.format_exc()}"
                        print(error_msg)
                        QMessageBox.warning(
                            self,
                            "保存エラー",
                            f"ステータス理由の保存に失敗しました。\nSKU: {sku_val}\nエラー: {str(e)}"
                        )

                    # スナップショットも保存（次回起動時に理由が消えないようにする）
                    try:
                        self.save_purchase_snapshot()
                    except Exception as e:
                        print(f"スナップショット保存エラー(ステータス理由変更): {e}")
            
            self.purchase_table.itemChanged.connect(on_item_changed)
        
        # デフォルトで仕入れ日列を降順でソート
        # 仕入れ日列のインデックスを取得
        purchase_date_col_idx = None
        for col_idx, col_name in enumerate(columns):
            if col_name == "仕入れ日" or col_name.upper() == "PURCHASE_DATE":
                purchase_date_col_idx = col_idx
                break
        
        # 仕入れ日列が見つかった場合は降順でソート
        if purchase_date_col_idx is not None:
            # 仕入れ日列で降順ソート
            self.purchase_table.sortItems(purchase_date_col_idx, Qt.DescendingOrder)
        
        # 表示モードに応じた列の表示/非表示を設定（必ず実行）
        if not hasattr(self, 'purchase_view_mode'):
            # デフォルトで全表示
            self.purchase_view_mode = "all"
        self._update_column_visibility()

        # 再描画のためソートを有効化し、シグナルを戻す
        self.purchase_table.setSortingEnabled(True)
        self.purchase_table.blockSignals(False)
        self.purchase_table.viewport().update()

    def _get_record_value(self, record: Dict[str, Any], keys: List[str]) -> Any:
        """大文字小文字を無視して値を取得"""
        for key in keys:
            for r_key, value in record.items():
                if r_key.upper() == key.upper():
                    return value
        return None

    def _truncate_text(self, text: str, limit: int) -> str:
        """テキストを指定文字数で丸める"""
        if len(text) <= limit:
            return text
        return text[:limit] + "..."
    
    def _update_row_color_by_status(self, row: int, status: str):
        """ステータスに応じて行の背景色を設定"""
        from PySide6.QtGui import QColor
        
        status = str(status).lower() if status else "ready"
        
        # ステータスに応じた色を設定
        color_map = {
            "ready": QColor(50, 50, 50),  # 通常（デフォルトの背景色）
            "damaged": QColor(80, 30, 30),  # 破損：赤系
            "unlistable": QColor(80, 50, 20),  # 登録不可：オレンジ系
            "storage": QColor(20, 30, 80),  # 保管中：青系
            "pending": QColor(80, 70, 20),  # 次回出品予定：黄色系
        }
        
        bg_color = color_map.get(status, QColor(50, 50, 50))
        
        # 行全体の背景色を設定
        for col in range(self.purchase_table.columnCount()):
            item = self.purchase_table.item(row, col)
            if item:
                item.setBackground(bg_color)
            else:
                # セルウィジェットがある場合（ステータス列など）
                widget = self.purchase_table.cellWidget(row, col)
                if widget:
                    widget.setStyleSheet(f"background-color: rgb({bg_color.red()}, {bg_color.green()}, {bg_color.blue()});")

    def _show_purchase_context_menu(self, position):
        """コンテキストメニューを表示"""
        menu = QMenu()
        copy_action = menu.addAction("選択範囲をコピー")
        copy_action.triggered.connect(self._copy_selection_to_clipboard)
        menu.addSeparator()
        amazon_action = menu.addAction("Amazon商品ページを開く")
        amazon_action.triggered.connect(self._open_amazon_link)
        keepa_action = menu.addAction("Keepaを開く")
        keepa_action.triggered.connect(self._open_keepa_link)
        menu.addSeparator()
        copy_sku_action = menu.addAction("SKUをコピー")
        copy_sku_action.triggered.connect(self._copy_sku)
        copy_asin_action = menu.addAction("ASINをコピー")
        copy_asin_action.triggered.connect(self._copy_asin)
        menu.exec_(self.purchase_table.viewport().mapToGlobal(position))

    def _copy_selection_to_clipboard(self):
        selection = self.purchase_table.selectedRanges()
        if not selection:
            return
        text = ""
        for r in range(selection[0].topRow(), selection[0].bottomRow() + 1):
            row_text = []
            for c in range(selection[0].leftColumn(), selection[0].rightColumn() + 1):
                item = self.purchase_table.item(r, c)
                row_text.append(item.text() if item else "")
            text += "\t".join(row_text) + "\n"
        QApplication.clipboard().setText(text)

    def _open_amazon_link(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        asin = self._get_value_from_row(row, ["ASIN", "asin"])
        if asin:
            url = f"https://www.amazon.co.jp/dp/{asin}"
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.warning(self, "エラー", "ASINが見つかりません。")

    def _open_keepa_link(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        asin = self._get_value_from_row(row, ["ASIN", "asin"])
        if asin:
            url = f"https://keepa.com/#!product/5-{asin}"
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.warning(self, "エラー", "ASINが見つかりません。")

    def _copy_sku(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        sku = self._get_value_from_row(row, ["SKU", "sku"])
        if sku:
            QApplication.clipboard().setText(sku)

    def _copy_asin(self):
        row = self.purchase_table.currentRow()
        if row < 0:
            return
        asin = self._get_value_from_row(row, ["ASIN", "asin"])
        if asin:
            QApplication.clipboard().setText(asin)

    def on_purchase_table_cell_clicked(self, row: int, col: int):
        """仕入DBテーブルのセルクリック時の処理（レシート画像をクリックしたときに画像を表示、ステータス理由をクリックしたときに編集モードに入る）"""
        header = self.purchase_table.horizontalHeaderItem(col)
        if not header:
            return
        
        header_text = header.text()
        
        # ステータス理由列をクリックしたときに編集モードに入る
        if header_text == "ステータス理由":
            item = self.purchase_table.item(row, col)
            if item and (item.flags() & Qt.ItemIsEditable):
                # 編集モードに入る（少し遅延を入れて確実に編集モードに入るようにする）
                QApplication.processEvents()
                self.purchase_table.editItem(item)
            return
        if header_text == "レシート画像":
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            receipt_image_name = item.text().strip()
            if not receipt_image_name:
                QMessageBox.information(self, "情報", "レシート画像が設定されていません。")
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            
            # UserRoleにファイルパスがない、またはファイルが存在しない場合は、テキストから再検索
            file_path_found = False
            if file_path:
                from pathlib import Path
                file_path_obj = Path(file_path)
                # ファイルパスが存在するか確認
                if file_path_obj.exists() and file_path_obj.is_file():
                    file_path_found = True
                else:
                    # UserRoleに保存されている値がファイル名の可能性があるので、再検索
                    file_path = None
            
            # 再検索が必要な場合
            receipt_info = None
            if not file_path_found:
                receipt_info = self.receipt_db.find_by_file_name(receipt_image_name)
                if receipt_info:
                    # original_file_pathを優先、なければfile_path
                    file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path')
            
            if file_path:
                from pathlib import Path
                image_file = Path(file_path)
                if image_file.exists() and image_file.is_file():
                    # OSのデフォルトアプリで画像を開く
                    file_url = QUrl.fromLocalFile(str(image_file.absolute()))
                    if not QDesktopServices.openUrl(file_url):
                        QMessageBox.warning(self, "警告", f"画像ファイルを開けませんでした:\n{file_path}")
                else:
                    # ファイルが存在しない場合の詳細メッセージ
                    if receipt_info:
                        QMessageBox.warning(
                            self, "警告",
                            f"レシート画像のファイルが見つかりません:\n\n"
                            f"ファイル名: {receipt_image_name}\n"
                            f"ファイルパス: {file_path}\n\n"
                            f"レシートDBには登録されていますが、\n"
                            f"ファイルが削除されているか、\n"
                            f"パスが変更されている可能性があります。"
                        )
                    else:
                        QMessageBox.warning(
                            self, "警告",
                            f"レシート画像が見つかりません:\n\n"
                            f"ファイル名: {receipt_image_name}\n\n"
                            f"レシートDBに登録されていない可能性があります。"
                        )
            else:
                QMessageBox.information(
                    self, "情報",
                    f"レシート画像の情報を取得できませんでした:\n\n"
                    f"ファイル名: {receipt_image_name}"
                )
        elif header_text == "保証書画像":
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            warranty_image_name = item.text().strip()
            if not warranty_image_name:
                QMessageBox.information(self, "情報", "保証書画像が設定されていません。")
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            
            # UserRoleにファイルパスがない、またはファイルが存在しない場合は、テキストから再検索
            file_path_found = False
            receipt_info = None
            warranty_info = None
            
            if file_path:
                from pathlib import Path
                file_path_obj = Path(file_path)
                # ファイルパスが存在するか確認
                if file_path_obj.exists() and file_path_obj.is_file():
                    file_path_found = True
                else:
                    # UserRoleに保存されている値がファイル名の可能性があるので、再検索
                    file_path = None
            
            # 再検索が必要な場合
            if not file_path_found:
                # まずレシートDBから保証書を検索（ファイル名で検索）
                receipt_info = self.receipt_db.find_by_file_name(warranty_image_name)
                if receipt_info:
                    # original_file_pathを優先、なければfile_path
                    file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path')
                else:
                    # レシートDBで見つからない場合は、保証書DBから検索
                    sku = self._get_value_from_row(row, ["SKU", "sku"])
                    if sku:
                        try:
                            warranties = self.warranty_db.list_by_sku(sku)
                            if warranties:
                                warranty_info = warranties[0]
                                file_path = warranty_info.get('file_path', '')
                        except Exception:
                            pass
            
            if file_path:
                from pathlib import Path
                image_file = Path(file_path)
                if image_file.exists() and image_file.is_file():
                    # OSのデフォルトアプリで画像を開く
                    file_url = QUrl.fromLocalFile(str(image_file.absolute()))
                    if not QDesktopServices.openUrl(file_url):
                        QMessageBox.warning(self, "警告", f"画像ファイルを開けませんでした:\n{file_path}")
                else:
                    # ファイルが存在しない場合の詳細メッセージ
                    if receipt_info or warranty_info:
                        QMessageBox.warning(
                            self, "警告",
                            f"保証書画像のファイルが見つかりません:\n\n"
                            f"ファイル名: {warranty_image_name}\n"
                            f"ファイルパス: {file_path}\n\n"
                            f"データベースには登録されていますが、\n"
                            f"ファイルが削除されているか、\n"
                            f"パスが変更されている可能性があります。"
                        )
                    else:
                        QMessageBox.warning(
                            self, "警告",
                            f"保証書画像が見つかりません:\n\n"
                            f"ファイル名: {warranty_image_name}\n\n"
                            f"レシートDBまたは保証書DBに登録されていない可能性があります。"
                        )
            else:
                QMessageBox.information(
                    self, "情報",
                    f"保証書画像の情報を取得できませんでした:\n\n"
                    f"ファイル名: {warranty_image_name}"
                )
        elif header_text and header_text.startswith("画像") and header_text[2:].isdigit():
            # 画像1～6のクリック処理
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            
            if file_path:
                from pathlib import Path
                image_file = Path(file_path)
                if image_file.exists():
                    # 画像を表示
                    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
                    from PySide6.QtGui import QPixmap
                    
                    dialog = QDialog(self)
                    dialog.setWindowTitle(f"{header_text}: {image_file.name}")
                    layout = QVBoxLayout(dialog)
                    
                    label = QLabel()
                    pixmap = QPixmap(str(file_path))
                    if not pixmap.isNull():
                        # 画像を適切なサイズにリサイズ（最大800x600）
                        scaled_pixmap = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        label.setPixmap(scaled_pixmap)
                    else:
                        label.setText("画像を読み込めませんでした。")
                    
                    layout.addWidget(label)
                    dialog.exec_()
                else:
                    QMessageBox.warning(self, "警告", f"画像ファイルが見つかりません:\n{file_path}")
            else:
                QMessageBox.information(self, "情報", f"{header_text}が設定されていません。")
    
    def _get_value_from_row(self, row: int, keys: List[str]) -> Optional[str]:
        for col in range(self.purchase_table.columnCount()):
            header = self.purchase_table.horizontalHeaderItem(col).text()
            if header in keys:
                item = self.purchase_table.item(row, col)
                return item.text() if item else None
            for key in keys:
                if header.upper() == key.upper():
                    item = self.purchase_table.item(row, col)
                    return item.text() if item else None
        return None

    def _infer_warranty_from_comment(self, row: Dict[str, Any]) -> Optional[str]:
        comment = str(row.get("コメント") or row.get("condition_note") or "")
        match = re.search(r"保証.*?(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", comment)
        if match:
            return match.group(1)
        return None
        
    def _calculate_product_name_width(self) -> int:
        return 300
