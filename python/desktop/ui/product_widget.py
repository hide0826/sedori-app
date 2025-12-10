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

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel, QTabWidget, QHeaderView, QFileDialog, QMenu, QApplication,
    QAbstractItemView
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor, QCursor

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
            "レシート画像",
            "保証書画像",  # 保証書IDから変更
            "保証期間",
            "保証最終日"  # 新規追加
        ]
        
        # その他の追加カラム
        extra_columns = [
            # 画像列
            "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
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
        self.import_inventory_button = QPushButton("仕入管理データを取り込み")
        self.import_inventory_button.clicked.connect(self.on_import_inventory)
        controls_layout.addWidget(self.import_inventory_button)

        self.delete_purchase_row_button = QPushButton("行削除")
        self.delete_purchase_row_button.clicked.connect(self.on_delete_purchase_row)
        controls_layout.addWidget(self.delete_purchase_row_button)

        self.delete_all_purchase_button = QPushButton("全行削除")
        self.delete_all_purchase_button.clicked.connect(self.on_delete_all_purchase)
        controls_layout.addWidget(self.delete_all_purchase_button)

        self.purchase_count_label = QLabel("保存件数: 0件")
        controls_layout.addWidget(self.purchase_count_label)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        # 仕入DBテーブル
        self.purchase_table = DraggableTableWidget()  # ドラッグ対応テーブルに変更
        self.purchase_table.setAlternatingRowColors(True)
        self.purchase_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.purchase_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
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
                        item.setForeground(Qt.blue)
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
        self.purchase_records = records
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
        
        if not hasattr(self, 'purchase_all_records'):
            self.purchase_all_records = []

        if not (date_query or sku_query or asin_query or jan_query):
            self.purchase_records = list(self.purchase_all_records)
            self.populate_purchase_table(self.purchase_records)
            self.update_purchase_count_label()
            return
            
        filtered_records = []
        for record in self.purchase_all_records:
            match = True
            if date_query:
                record_date = str(record.get("仕入れ日") or "")
                if not self._date_matches(record_date, date_query):
                    match = False
            if match and sku_query:
                record_sku = str(record.get("SKU") or record.get("sku") or "").lower()
                if sku_query not in record_sku:
                    match = False
            if match and asin_query:
                record_asin = str(record.get("ASIN") or record.get("asin") or "").lower()
                if asin_query not in record_asin:
                    match = False
            if match and jan_query:
                record_jan = str(record.get("JAN") or record.get("jan") or "").lower()
                if jan_query not in record_jan:
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
        self.purchase_records = list(self.purchase_all_records) if hasattr(self, 'purchase_all_records') else []
        self.populate_purchase_table(self.purchase_records)
        self.update_purchase_count_label()
    
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
                except Exception as e:
                    print(f"古物台帳情報取得エラー(SKU={sku}): {e}")

            augmented.append(row)
        return augmented

    def populate_purchase_table(self, records: List[Dict[str, Any]]):
        """仕入DBテーブルにレコードを反映"""
        from pathlib import Path
        
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
                        # 画像ファイル名で検索（拡張子なし）
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
                        item.setForeground(Qt.blue)
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)
                    else:
                        item = QTableWidgetItem("")
                else:
                    item = QTableWidgetItem(str(value))
                self.purchase_table.setItem(row, col, item)

        # 各列をリサイズ可能に設定
        header = self.purchase_table.horizontalHeader()
        for col_idx in range(len(columns)):
            header.setSectionResizeMode(col_idx, QHeaderView.Interactive)
        
        # 列幅のみを復元（リサイズモードは変更しない）
        restore_table_column_widths(self.purchase_table, "ProductWidget/PurchaseTableColumnWidths")

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
        """仕入DBテーブルのセルクリック時の処理（レシート画像をクリックしたときに画像を表示）"""
        header = self.purchase_table.horizontalHeaderItem(col)
        if not header:
            return
        
        header_text = header.text()
        if header_text == "レシート画像":
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            
            # UserRoleにファイルパスがない、またはファイルが存在しない場合は、テキストから再検索
            if not file_path:
                # UserRoleにない場合は、テキストから検索
                receipt_image_name = item.text().strip()
                if receipt_image_name:
                    receipt_info = self.receipt_db.find_by_file_name(receipt_image_name)
                    if receipt_info:
                        # original_file_pathを優先、なければfile_path
                        file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path')
            else:
                # UserRoleにファイル名（文字列）が保存されている場合は、再検索
                from pathlib import Path
                file_path_obj = Path(file_path)
                if not file_path_obj.exists():
                    # ファイルが存在しない場合は、テキストから再検索
                    receipt_image_name = item.text().strip()
                    if receipt_image_name:
                        receipt_info = self.receipt_db.find_by_file_name(receipt_image_name)
                        if receipt_info:
                            # original_file_pathを優先、なければfile_path
                            file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path')
            
            if file_path:
                from pathlib import Path
                image_file = Path(file_path)
                if image_file.exists():
                    # 画像を表示
                    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
                    from PySide6.QtGui import QPixmap
                    
                    dialog = QDialog(self)
                    dialog.setWindowTitle("レシート画像")
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
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "警告", f"画像ファイルが見つかりません:\n{file_path}")
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "情報", "レシート画像が設定されていません。")
        elif header_text == "保証書画像":
            item = self.purchase_table.item(row, col)
            if not item:
                return
            
            # ファイルパスを取得（UserRoleに保存されている）
            file_path = item.data(Qt.UserRole)
            
            # UserRoleにファイルパスがない、またはファイルが存在しない場合は、テキストから再検索
            if not file_path:
                # UserRoleにない場合は、テキストから検索（レシートDBから検索）
                warranty_image_name = item.text().strip()
                if warranty_image_name:
                    # レシートDBから保証書を検索（ファイル名で検索）
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
                                    warranty = warranties[0]
                                    file_path = warranty.get('file_path', '')
                            except Exception:
                                pass
            else:
                # UserRoleにファイル名（文字列）が保存されている場合は、再検索
                from pathlib import Path
                file_path_obj = Path(file_path)
                if not file_path_obj.exists():
                    # ファイルが存在しない場合は、テキストから再検索（レシートDBから検索）
                    warranty_image_name = item.text().strip()
                    if warranty_image_name:
                        # レシートDBから保証書を検索（ファイル名で検索）
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
                                        warranty = warranties[0]
                                        file_path = warranty.get('file_path', '')
                                except Exception:
                                    pass
            
            if file_path:
                from pathlib import Path
                image_file = Path(file_path)
                if image_file.exists():
                    # 画像を表示
                    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
                    from PySide6.QtGui import QPixmap
                    
                    dialog = QDialog(self)
                    dialog.setWindowTitle("保証書画像")
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
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "警告", f"画像ファイルが見つかりません:\n{file_path}")
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "情報", "保証書画像が設定されていません。")
    
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
