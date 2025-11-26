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
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel, QTabWidget, QHeaderView, QFileDialog, QMenu, QApplication,
    QAbstractItemView
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor, QCursor

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import json
import logging
from database.product_db import ProductDatabase
from database.warranty_db import WarrantyDatabase
from database.product_purchase_db import ProductPurchaseDatabase


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
            if header and header.text() == "レシートID" and item.text().strip():
                self.setCursor(QCursor(Qt.PointingHandCursor))
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
        
        # レシートID列かどうかを確認
        col = self.currentColumn()
        header = self.horizontalHeaderItem(col)
        if header and header.text() == "レシートID":
            receipt_id = item.text().strip()
            if receipt_id:
                # ドラッグデータを作成
                drag = QDrag(self)
                mime_data = QMimeData()
                # テキストデータとしてレシートIDを設定
                mime_data.setText(receipt_id)
                drag.setMimeData(mime_data)
                # ドラッグを開始
                drag.exec_(Qt.CopyAction)
                return
        # レシートID列以外は通常のドラッグ処理
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
        self.purchase_db = ProductPurchaseDatabase()
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

    def _resolve_inventory_columns(self) -> List[str]:
        """仕入管理タブの列構成を取得（未設定時はデフォルト）"""
        if self.inventory_widget is not None:
            headers = getattr(self.inventory_widget, "column_headers", None)
            if headers:
                # コピーして改変から保護
                base = list(headers)
                for extra in ["保証期間", "レシートID", "保証書ID"]:
                    if extra not in base:
                        base.append(extra)
                # 画像1〜6を追加（既に存在しない場合のみ）
                for i in range(1, 7):
                    image_col = f"画像{i}"
                    if image_col not in base:
                        base.append(image_col)
                return base
        return [
            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "コメント",
            "発送方法", "仕入先", "コンディション説明", "保証期間", "レシートID", "保証書ID",
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6"
        ]

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

    def get_all_purchase_records(self) -> List[Dict[str, Any]]:
        """現在のすべての仕入レコードを返す"""
        return self.purchase_all_records

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
        search_layout = QHBoxLayout(search_group)
        
        search_layout.addWidget(QLabel("日付:"))
        self.purchase_search_date = QLineEdit()
        self.purchase_search_date.setPlaceholderText("yyyy-mm-dd または yyyy/mm/dd")
        search_layout.addWidget(self.purchase_search_date)
        
        search_layout.addWidget(QLabel("SKU:"))
        self.purchase_search_sku = QLineEdit()
        self.purchase_search_sku.setPlaceholderText("SKUで検索")
        search_layout.addWidget(self.purchase_search_sku)
        
        search_layout.addWidget(QLabel("ASIN:"))
        self.purchase_search_asin = QLineEdit()
        self.purchase_search_asin.setPlaceholderText("ASINで検索")
        search_layout.addWidget(self.purchase_search_asin)
        
        search_layout.addWidget(QLabel("JAN:"))
        self.purchase_search_jan = QLineEdit()
        self.purchase_search_jan.setPlaceholderText("JANで検索")
        search_layout.addWidget(self.purchase_search_jan)
        
        self.purchase_search_button = QPushButton("検索")
        self.purchase_search_button.clicked.connect(self.search_purchase_data)
        search_layout.addWidget(self.purchase_search_button)
        
        self.purchase_clear_search_button = QPushButton("クリア")
        self.purchase_clear_search_button.clicked.connect(self.clear_purchase_search)
        search_layout.addWidget(self.purchase_clear_search_button)
        
        layout.addWidget(search_group)

        controls = QHBoxLayout()
        self.import_purchase_button = QPushButton("仕入管理データを取り込み")
        self.import_purchase_button.clicked.connect(self.import_purchase_data)
        controls.addWidget(self.import_purchase_button)
        self.delete_selected_button = QPushButton("行削除")
        self.delete_selected_button.clicked.connect(self.delete_selected_purchase_row)
        controls.addWidget(self.delete_selected_button)
        self.clear_all_button = QPushButton("全行削除")
        self.clear_all_button.clicked.connect(self.clear_all_purchase_rows)
        controls.addWidget(self.clear_all_button)
        
        # 保存件数表示
        self.purchase_count_label = QLabel("")
        controls.addWidget(self.purchase_count_label)
        
        controls.addStretch()
        layout.addLayout(controls)

        self.purchase_table = DraggableTableWidget()
        self.purchase_table.setColumnCount(len(self.purchase_columns))
        self.purchase_table.setHorizontalHeaderLabels(self.purchase_columns)
        self.purchase_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.purchase_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.purchase_table.setSelectionMode(QTableWidget.SingleSelection)
        self.purchase_table.verticalHeader().setVisible(False)
        self.purchase_table.setTextElideMode(Qt.ElideNone)
        self.purchase_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._apply_purchase_column_resize(self.purchase_columns)
        # セルクリックイベントを接続（レシートID列のクリック処理用）
        self.purchase_table.cellClicked.connect(self.on_purchase_table_cell_clicked)
        self.purchase_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.purchase_table.customContextMenuRequested.connect(self.on_purchase_table_context_menu)
        layout.addWidget(self.purchase_table)
        
        # 全データを保持（検索用）
        self.purchase_all_records: List[Dict[str, Any]] = []

    # --- 販売DBタブ ---
    def setup_sales_tab(self):
        layout = QVBoxLayout(self.sales_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        info_label = QLabel("販売DB（仮）\n※後日項目を確定予定。現在はサンプル列のみ表示しています。")
        info_label.setStyleSheet("color: #cccccc;")
        layout.addWidget(info_label)

        self.sales_table = QTableWidget()
        sales_columns = [
            "販売ID", "SKU", "販売日", "販売価格", "数量", "手数料",
            "利益", "販売先", "備考"
        ]
        self.sales_table.setColumnCount(len(sales_columns))
        self.sales_table.setHorizontalHeaderLabels(sales_columns)
        self.sales_table.horizontalHeader().setStretchLastSection(True)
        self.sales_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sales_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sales_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sales_table.verticalHeader().setVisible(False)
        layout.addWidget(self.sales_table)

    # ===== データ読み込み・更新 =====

    def load_products(self):
        products = self.db.list_all()
        self.table.setRowCount(len(products))

        for row, product in enumerate(products):
            def _set(col: int, value: Optional[str]):
                item = QTableWidgetItem("" if value is None else str(value))
                item.setData(Qt.UserRole, product.get("sku"))
                self.table.setItem(row, col, item)

            _set(0, product.get("sku"))
            _set(1, product.get("product_name"))
            _set(2, product.get("jan"))
            _set(3, product.get("asin"))
            _set(4, product.get("purchase_date"))
            _set(5, product.get("purchase_price"))
            _set(6, product.get("quantity"))
            _set(7, product.get("store_code"))
            _set(8, product.get("store_name"))
            _set(9, product.get("warranty_period_days"))
            _set(10, product.get("warranty_until"))
            
            # 画像1〜6の表示（ファイル名のみ表示）
            for i in range(1, 7):
                image_key = f"image_{i}"
                image_path = product.get(image_key) or ""
                if image_path:
                    # ファイル名のみ表示
                    image_name = Path(image_path).name
                    item = QTableWidgetItem(image_name)
                    item.setData(Qt.UserRole, image_path)  # フルパスをUserRoleに保存
                    item.setToolTip(f"クリックで画像を開く\n{image_path}")
                    item.setFlags(item.flags() | Qt.ItemIsEnabled)
                    self.table.setItem(row, 10 + i, item)
                else:
                    item = QTableWidgetItem("")
                    self.table.setItem(row, 10 + i, item)
    
    def on_product_table_cell_clicked(self, row: int, col: int):
        """商品DBテーブルのセルクリックイベントハンドラ"""
        if col < 11:
            return  # 通常の列は処理しない
        
        item = self.table.item(row, col)
        if item is None:
            return
        
        # 画像列（11〜16列目）の場合
        if 11 <= col <= 16:
            image_path = item.data(Qt.UserRole)
            if image_path:
                file_path = Path(image_path)
                if file_path.exists():
                    # 画像ファイルを開く
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
                else:
                    QMessageBox.warning(
                        self, "エラー",
                        f"画像ファイルが見つかりません:\n{file_path}"
                    )

    def load_purchase_data(self, records: Optional[List[Dict[str, Any]]] = None):
        """仕入DBテーブルを更新（recordsがNoneの場合は空で初期化）"""
        if records is not None:
            self.purchase_records = records
            self.purchase_all_records = records.copy()  # 検索用に全データを保持
        else:
            self.purchase_all_records = self.purchase_records.copy() if self.purchase_records else []
        self.populate_purchase_table(self.purchase_records)
        if hasattr(self, 'update_purchase_count_label'):
            self.update_purchase_count_label()

    def load_sales_data(self, records: Optional[List[Dict[str, Any]]] = None):
        """販売DBテーブルを初期表示（暫定データ）"""
        if records is not None:
            self.sales_records = records
        if not self.sales_records:
            # 仮データを1件表示
            self.sales_records = [{
                "販売ID": "SAMPLE-0001",
                "SKU": "SAMPLE-SKU",
                "販売日": "2025-01-01",
                "販売価格": 12345,
                "数量": 1,
                "手数料": 1000,
                "利益": 3045,
                "販売先": "Amazon",
                "備考": "サンプルデータ（後で置き換え）"
            }]
        columns = [
            "販売ID", "SKU", "販売日", "販売価格", "数量", "手数料",
            "利益", "販売先", "備考"
        ]
        self.sales_table.setRowCount(len(self.sales_records))
        self.sales_table.setColumnCount(len(columns))
        self.sales_table.setHorizontalHeaderLabels(columns)
        for row, record in enumerate(self.sales_records):
            for col, header in enumerate(columns):
                value = record.get(header, "")
                self.sales_table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))

    def _get_selected_sku(self) -> Optional[str]:
        selected = self.table.selectedItems()
        if not selected:
            return None
        return selected[0].data(Qt.UserRole)

    def on_add_product(self):
        dialog = ProductEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data:
                return
            try:
                self.db.upsert(data)
                QMessageBox.information(self, "登録完了", "商品を追加しました。")
                self.load_products()
            except Exception as e:
                QMessageBox.critical(self, "登録エラー", f"商品追加に失敗しました:\n{e}")

    def on_edit_product(self):
        sku = self._get_selected_sku()
        if not sku:
            QMessageBox.warning(self, "選択してください", "編集する商品を選択してください。")
            return
        product = self.db.get_by_sku(sku)
        if not product:
            QMessageBox.warning(self, "データなし", "対象の商品データが見つかりません。")
            return
        dialog = ProductEditDialog(self, product=product)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data:
                return
            try:
                self.db.upsert(data)
                QMessageBox.information(self, "更新完了", "商品情報を更新しました。")
                self.load_products()
            except Exception as e:
                QMessageBox.critical(self, "更新エラー", f"商品更新に失敗しました:\n{e}")

    def on_delete_product(self):
        sku = self._get_selected_sku()
        if not sku:
            QMessageBox.warning(self, "選択してください", "削除する商品を選択してください。")
            return
        ret = QMessageBox.question(
            self, "確認", f"SKU {sku} を削除しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return
        try:
            success = self.db.delete(sku)
            if success:
                QMessageBox.information(self, "削除完了", "商品を削除しました。")
            else:
                QMessageBox.warning(self, "削除できません", "対象の商品が見つかりませんでした。")
            self.load_products()
        except Exception as e:
            QMessageBox.critical(self, "削除エラー", f"商品削除に失敗しました:\n{e}")

    # ===== 仕入DBロジック =====

    def import_purchase_data(self):
        """仕入管理タブからデータを取り込み"""
        records = self._collect_inventory_records()
        if records is None:
            return
        
        # 既存データとマージ（重複チェック）
        existing_skus = {r.get("SKU") or r.get("sku", "") for r in self.purchase_all_records if r.get("SKU") or r.get("sku")}
        new_records = []
        updated_count = 0
        
        for record in records:
            sku = record.get("SKU") or record.get("sku", "")
            if sku and sku in existing_skus:
                # 既存データを更新（同じSKUの既存レコードを置き換え）
                for i, existing in enumerate(self.purchase_all_records):
                    existing_sku = existing.get("SKU") or existing.get("sku", "")
                    if existing_sku == sku:
                        self.purchase_all_records[i] = record
                        updated_count += 1
                        break
            else:
                # 新規データを追加
                new_records.append(record)
        
        # 新規データを追加
        self.purchase_all_records.extend(new_records)
        self.purchase_records = self.purchase_all_records.copy()
        
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
        
        try:
            self.purchase_db.save_snapshot("自動保存(仕入DB)", self.purchase_all_records)
        except Exception as e:
            print(f"仕入DB自動保存失敗: {e}")
        
        message = f"{len(new_records)}件の新規データを追加"
        if updated_count > 0:
            message += f"、{updated_count}件を更新"
        message += f"しました。（合計: {len(self.purchase_all_records)}件）"
        QMessageBox.information(self, "取り込み完了", message)

    def delete_selected_purchase_row(self):
        """デバッグ用: 選択行を削除"""
        row = self.purchase_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "行削除", "削除する行を選択してください。")
            return
        
        reply = QMessageBox.question(
            self, "確認", "選択した行を削除しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if 0 <= row < len(self.purchase_records):
                deleted_record = self.purchase_records[row]
                # 全データからも削除
                sku = deleted_record.get("SKU") or deleted_record.get("sku", "")
                if sku:
                    self.purchase_all_records = [
                        r for r in self.purchase_all_records
                        if (r.get("SKU") or r.get("sku", "")) != sku
                    ]
                del self.purchase_records[row]
                self.populate_purchase_table(self.purchase_records)
                self.update_purchase_count_label()
                
                # スナップショットも更新
                try:
                    self.purchase_db.save_snapshot("自動保存(仕入DB)", self.purchase_all_records)
                except Exception as e:
                    print(f"仕入DB自動保存失敗: {e}")

    def clear_all_purchase_rows(self):
        """デバッグ用: 全行削除"""
        reply = QMessageBox.question(
            self, "確認", "すべての仕入DBデータを削除しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.purchase_table.setRowCount(0)
            self.purchase_records = []
            self.purchase_all_records = []
            self.update_purchase_count_label()

    def restore_latest_purchase_snapshot(self):
        """最新の仕入DBスナップショットを読み込み"""
        try:
            snapshots = self.purchase_db.list_snapshots()
            if not snapshots:
                return
            latest_id = snapshots[0]["id"]
            latest = self.purchase_db.get_snapshot(latest_id)
            if latest and latest.get("data"):
                self.purchase_records = latest["data"]
                self.purchase_all_records = latest["data"].copy()  # 検索用に全データを保持
                self.update_purchase_count_label()
        except Exception as e:
            print(f"仕入DBスナップショット読み込み失敗: {e}")
    
    def search_purchase_data(self):
        """仕入DBデータを検索"""
        search_date = self.purchase_search_date.text().strip()
        search_sku = self.purchase_search_sku.text().strip()
        search_asin = self.purchase_search_asin.text().strip()
        search_jan = self.purchase_search_jan.text().strip()
        
        # 検索条件がすべて空の場合は全件表示
        if not any([search_date, search_sku, search_asin, search_jan]):
            self.purchase_records = self.purchase_all_records.copy()
            self.populate_purchase_table(self.purchase_records)
            self.update_purchase_count_label()
            return
        
        # 日付の正規化
        normalized_date = None
        if search_date:
            normalized_date = self._normalize_date_for_search(search_date)
        
        filtered_records = []
        for record in self.purchase_all_records:
            match = True
            
            # 日付検索
            if normalized_date:
                record_date = record.get("仕入れ日") or record.get("purchase_date") or ""
                if not self._date_matches(record_date, normalized_date):
                    match = False
            
            # SKU検索
            if match and search_sku:
                record_sku = str(record.get("SKU") or record.get("sku") or "").upper()
                if search_sku.upper() not in record_sku:
                    match = False
            
            # ASIN検索
            if match and search_asin:
                record_asin = str(record.get("ASIN") or record.get("asin") or "").upper()
                if search_asin.upper() not in record_asin:
                    match = False
            
            # JAN検索
            if match and search_jan:
                record_jan = str(record.get("JAN") or record.get("jan") or "").upper()
                if search_jan.upper() not in record_jan:
                    match = False
            
            if match:
                filtered_records.append(record)
        
        self.purchase_records = filtered_records
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
    
    def clear_purchase_search(self):
        """検索条件をクリアして全件表示"""
        self.purchase_search_date.clear()
        self.purchase_search_sku.clear()
        self.purchase_search_asin.clear()
        self.purchase_search_jan.clear()
        self.purchase_records = self.purchase_all_records.copy()
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
    
    def update_purchase_count_label(self):
        """保存件数ラベルを更新"""
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
        
        # 区切り文字を統一
        date_str = date_str.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-").replace("日", "")
        
        # yyyy-mm-dd形式に変換を試みる
        parts = date_str.split("-")
        if len(parts) >= 3:
            try:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])
                return f"{year:04d}-{month:02d}-{day:02d}"
            except ValueError:
                pass
        
        return date_str
    
    def _date_matches(self, record_date: str, search_date: str) -> bool:
        """日付が一致するかチェック（部分一致対応）"""
        if not record_date or not search_date:
            return False
        
        # 日付を正規化
        normalized_record = self._normalize_date_for_search(str(record_date))
        if not normalized_record:
            return False
        
        # 部分一致チェック（yyyy-mm-ddの形式で比較）
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
        """保証・レシート情報を付与"""
        augmented: List[Dict[str, Any]] = []
        for record in records:
            row = dict(record)
            sku = row.get("SKU") or row.get("sku")
            # コメントから保証期間を算出
            comment_warranty = self._infer_warranty_from_comment(row)
            if comment_warranty:
                row["保証期間"] = comment_warranty

            if sku:
                try:
                    product = self.db.get_by_sku(sku)
                except Exception:
                    product = None
                if product:
                    if ("保証期間" not in row or not row.get("保証期間")) and product.get("warranty_until"):
                        row["保証期間"] = product.get("warranty_until")
                    if "レシートID" not in row and product.get("receipt_id") is not None:
                        row["レシートID"] = product.get("receipt_id")
                    # 画像1〜6を追加
                    for i in range(1, 7):
                        image_key = f"image_{i}"
                        image_col = f"画像{i}"
                        if image_col not in row or not row.get(image_col):
                            image_path = product.get(image_key)
                            if image_path:
                                row[image_col] = image_path
                # 保証書情報は warranties テーブルを参照
                try:
                    warranties = self.warranty_db.list_by_sku(sku)
                except Exception:
                    warranties = []
                warranty_id = warranties[0]["id"] if warranties else None
                if "保証書ID" not in row and warranty_id is not None:
                    row["保証書ID"] = warranty_id
            augmented.append(row)
        return augmented

    def _apply_purchase_column_resize(self, columns: List[str]) -> None:
        """列幅を設定（商品名以外は自動調整）"""
        header = self.purchase_table.horizontalHeader()
        for idx, name in enumerate(columns):
            if name == "商品名":
                header.setSectionResizeMode(idx, QHeaderView.Fixed)
                header.resizeSection(idx, self._calculate_product_name_width())
            else:
                header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)

    def populate_purchase_table(self, records: List[Dict[str, Any]]):
        """仕入DBテーブルにレコードを反映"""
        base_columns = list(self.inventory_columns)
        if not base_columns:
            base_columns = self._resolve_inventory_columns()
        columns = list(base_columns)
        seen = set(col.upper() for col in columns)
        for record in records:
            for key in record.keys():
                upper_key = key.upper()
                if upper_key not in seen:
                    seen.add(upper_key)
                    columns.append(key)
        self.purchase_columns = columns
        self.purchase_table.setRowCount(len(records))
        self.purchase_table.setColumnCount(len(columns))
        self.purchase_table.setHorizontalHeaderLabels(columns)
        self._apply_purchase_column_resize(columns)

        for row, record in enumerate(records):
            for col, header in enumerate(columns):
                # レコードから値を取得（大文字小文字を無視して検索）
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
                elif header == "レシートID":
                    # レシートID列の特別処理
                    receipt_id_str = "" if value is None else str(value)
                    item = QTableWidgetItem(receipt_id_str)
                    if receipt_id_str:
                        # クリック可能にする（カーソルをポインターに変更）
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                        # ツールチップに画像ファイルパスを表示
                        receipt_info = self.receipt_db.find_by_receipt_id(receipt_id_str)
                        if receipt_info and receipt_info.get('file_path'):
                            file_path = receipt_info.get('file_path')
                            item.setToolTip(f"クリックで画像を開く\n{file_path}")
                            # レシートIDをUserRoleに保存（画像ファイルパス取得用）
                            item.setData(Qt.UserRole, file_path)
                        else:
                            item.setToolTip("レシートID: " + receipt_id_str)
                        # ドラッグ可能にする
                        item.setFlags(item.flags() | Qt.ItemIsDragEnabled)
                elif header and header.startswith("画像") and header[2:].isdigit():
                    # 画像1〜6列の特別処理
                    image_path = value or ""
                    if image_path:
                        # ファイル名のみ表示
                        image_name = Path(image_path).name
                        item = QTableWidgetItem(image_name)
                        item.setData(Qt.UserRole, image_path)  # フルパスをUserRoleに保存
                        item.setToolTip(f"クリックで画像を開く\n{image_path}")
                        item.setFlags(item.flags() | Qt.ItemIsEnabled)
                    else:
                        item = QTableWidgetItem("")
                else:
                    item = QTableWidgetItem("" if value is None else str(value))
                self.purchase_table.setItem(row, col, item)

    def on_purchase_table_cell_clicked(self, row: int, col: int):
        """仕入DBテーブルのセルクリックイベントハンドラ"""
        item = self.purchase_table.item(row, col)
        if item is None:
            return
        
        header = self.purchase_columns[col] if col < len(self.purchase_columns) else ""
        
        # 画像1〜6の列をクリックした場合
        if header and header.startswith("画像") and header[2:].isdigit():
            image_path = item.data(Qt.UserRole)
            if image_path:
                file_path = Path(image_path)
                if file_path.exists():
                    # 画像ファイルを開く
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
                else:
                    QMessageBox.warning(
                        self, "エラー",
                        f"画像ファイルが見つかりません:\n{file_path}"
                    )
            return
        
        # レシートID列をクリックした場合
        if header == "レシートID":
            receipt_id = item.text().strip()
            if not receipt_id:
                return
            
            # レシートIDから画像ファイルパスを取得
            receipt_info = self.receipt_db.find_by_receipt_id(receipt_id)
            if receipt_info and receipt_info.get('file_path'):
                file_path = Path(receipt_info.get('file_path'))
                if file_path.exists():
                    # 画像ファイルを開く
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
                else:
                    QMessageBox.warning(
                        self, "エラー",
                        f"レシート画像ファイルが見つかりません:\n{file_path}"
                    )
            else:
                QMessageBox.information(
                    self, "情報",
                    f"レシートID '{receipt_id}' に対応するレシート情報が見つかりません。"
                )

    def on_purchase_table_context_menu(self, pos):
        """仕入DBテーブルのコンテキストメニュー"""
        row = self.purchase_table.rowAt(pos.y())
        if row < 0:
            return
        record = self._get_purchase_record_by_row(row)
        if not record:
            return

        asin = self._get_record_value(record, ["ASIN", "asin"])
        sku = self._get_record_value(record, ["SKU", "sku"])

        menu = QMenu(self)

        copy_selection_action = menu.addAction("選択範囲をコピー")
        copy_selection_action.triggered.connect(self.copy_purchase_selection)

        menu.addSeparator()

        if asin:
            amazon_url = f"https://www.amazon.co.jp/dp/{asin}"
            keepa_url = f"https://keepa.com/#!product/5-{asin}"
            amazon_action = menu.addAction("Amazonで確認")
            amazon_action.triggered.connect(
                lambda checked=False, url=amazon_url: QDesktopServices.openUrl(QUrl(url))
            )
            keepa_action = menu.addAction("Keepaで確認")
            keepa_action.triggered.connect(
                lambda checked=False, url=keepa_url: QDesktopServices.openUrl(QUrl(url))
            )
        else:
            disabled = menu.addAction("ASINが設定されていません")
            disabled.setEnabled(False)

        if sku:
            copy_sku = menu.addAction(f"SKUをコピー ({sku})")
            copy_sku.triggered.connect(lambda text=sku: QApplication.clipboard().setText(text))

        menu.exec(self.purchase_table.viewport().mapToGlobal(pos))

    def copy_purchase_selection(self):
        """仕入DBテーブルの選択範囲をコピー"""
        selection_model = self.purchase_table.selectionModel()
        if not selection_model:
            return
        indexes = selection_model.selectedIndexes()
        if not indexes:
            return

        rows: Dict[int, Dict[int, str]] = {}
        min_col = min(index.column() for index in indexes)
        max_col = max(index.column() for index in indexes)

        for index in indexes:
            item = self.purchase_table.item(index.row(), index.column())
            value = item.text() if item else ""
            rows.setdefault(index.row(), {})[index.column()] = value

        lines = []
        for row in sorted(rows.keys()):
            row_data = []
            for col in range(min_col, max_col + 1):
                row_data.append(rows[row].get(col, ""))
            lines.append("\t".join(row_data))

        QApplication.clipboard().setText("\n".join(lines))
    
    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit]

    def _get_purchase_record_by_row(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self.purchase_records):
            return self.purchase_records[row]
        return None

    def _calculate_product_name_width(self) -> int:
        """商品名列で50文字を表示するための列幅を算出"""
        metrics = self.purchase_table.fontMetrics()
        sample_text = "W" * PRODUCT_NAME_DISPLAY_LIMIT
        width = metrics.horizontalAdvance(sample_text)
        return width + 40  # 余白ぶんを加算

    @staticmethod
    def _get_record_value(record: Dict[str, Any], keys: List[str]) -> str:
        for key in keys:
            value = record.get(key)
            if value not in (None, ""):
                return str(value)
            upper_key = key.upper()
            for actual_key, actual_value in record.items():
                if actual_key.upper() == upper_key and actual_value not in (None, ""):
                    return str(actual_value)
        return ""

    def _infer_warranty_from_comment(self, row: Dict[str, Any]) -> Optional[str]:
        """コメント欄から保証期間（月）を推定し、仕入日からの満了日を返す"""
        comment = row.get("コメント") or row.get("comment")
        if not comment:
            return None

        normalized = unicodedata.normalize("NFKC", str(comment))
        months = self._extract_warranty_months(normalized)
        if months is None:
            return None

        purchase_date_str = row.get("仕入れ日") or row.get("purchase_date")
        purchase_date = self._parse_purchase_date(purchase_date_str)
        if not purchase_date:
            return None

        end_date = self._add_months(purchase_date, months)
        return end_date.strftime("%Y-%m-%d")

    @staticmethod
    def _extract_warranty_months(text: str) -> Optional[int]:
        """コメントから保証期間（月数）を抽出"""
        patterns = [
            r'(\d+)\s*[ヶヵケかカｶ]?\s*(?:月|ヶ月|か月|カ月)\s*保証',
            r'保証\s*(\d+)\s*[ヶヵケかカｶ]?\s*(?:月|ヶ月|か月|カ月)',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue

        # 特殊表現
        if "半年保証" in text or "半年の保証" in text:
            return 6
        if "1年保証" in text or "一年保証" in text:
            return 12

        return None

    @staticmethod
    def _parse_purchase_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None

        # 一部フォーマット（年月日）を変換
        text = (
            text.replace("年", "/")
                .replace("月", "/")
                .replace("日", "")
        )
        text = text.replace("-", "/")
        text = text.replace(".", "/")

        # 時刻を分離
        candidates = [text]
        if " " in text:
            date_part, time_part = text.split(" ", 1)
            candidates = [
                f"{date_part} {time_part}",
                date_part
            ]
        else:
            candidates = [text]

        fmts = [
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ]

        for candidate in candidates:
            for fmt in fmts:
                try:
                    return datetime.strptime(candidate, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _add_months(base_date: datetime, months: int) -> datetime:
        month = base_date.month - 1 + months
        year = base_date.year + month // 12
        month = month % 12 + 1
        day = min(base_date.day, calendar.monthrange(year, month)[1])
        return datetime(year, month, day)

    def update_image_paths_for_jan(self, jan: str, image_paths: List[str], all_records: List[Dict[str, Any]], skip_existing: bool = True) -> Tuple[bool, int, Optional[Dict[str, Any]]]:
        """指定されたJANコードを持つ仕入DBレコードの画像パスを更新する
        
        Args:
            jan: JANコード
            image_paths: 追加する画像パスのリスト
            all_records: 全仕入レコードのリスト
            skip_existing: Trueの場合、既に登録されている画像はスキップ
        
        Returns:
            (成功フラグ, 追加された画像数, 更新後の仕入レコードのスナップショット)
        """
        if not jan or not image_paths:
            return False, 0, None

        # JANコードを正規化（文字列化して空白を除去）
        jan_normalized = str(jan).strip()

        # purchase_all_recordsからJANでレコードを検索（大文字小文字を無視、Noneチェック付き）
        target_record = None
        for r in all_records:
            record_jan = r.get("JAN") or r.get("jan")
            if record_jan:
                record_jan_normalized = str(record_jan).strip()
                if record_jan_normalized == jan_normalized:
                    target_record = r
                    break

        if not target_record:
            logging.warning(f"No purchase record found for JAN: {jan}")
            return False, 0, None

        # 既存の画像パスを取得
        existing_paths = set()
        if skip_existing:
            for i in range(1, 7):
                image_col = f"画像{i}"
                existing_path = target_record.get(image_col)
                if existing_path and str(existing_path).strip():
                    existing_paths.add(str(existing_path).strip())

        # 未登録の画像パスのみを抽出
        new_image_paths = []
        for path in image_paths:
            path_normalized = str(path).strip()
            if path_normalized and path_normalized not in existing_paths:
                new_image_paths.append(path_normalized)

        if not new_image_paths:
            # 全て既に登録済み
            return True, 0, dict(target_record)

        # 既存の画像パスをリストに変換（空欄をスキップ）
        current_images = []
        for i in range(1, 7):
            image_col = f"画像{i}"
            existing_path = target_record.get(image_col)
            if existing_path and str(existing_path).strip():
                current_images.append(str(existing_path).strip())

        # 新しい画像パスを追加（最大6枚まで）
        for path in new_image_paths:
            if len(current_images) >= 6:
                break
            current_images.append(path)

        # 更新するデータを準備（画像1から最大6まで）
        # カラム名は「画像1」「画像2」など
        for i in range(6):
            image_col = f"画像{i+1}"
            if i < len(current_images):
                target_record[image_col] = current_images[i]
            else:
                # 不要な画像列をクリア
                target_record[image_col] = None
            
        try:
            # メモリ上のデータを更新（target_recordはall_recordsの参照なので、直接変更で反映される）
            # purchase_all_recordsも更新（同じ参照）
            # UI更新
            self.populate_purchase_table(self.purchase_records)
            
            # スナップショットも更新（変更を永続化）
            try:
                self.purchase_db.save_snapshot("自動保存(画像紐付け)", self.purchase_all_records)
            except Exception as e:
                logging.error(f"仕入DBスナップショット保存失敗: {e}")
            
            return True, len(new_image_paths), dict(target_record)
        except Exception as e:
            logging.error(f"Failed to update image paths in memory: {e}")
            return False, 0, None
            
