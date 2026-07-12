#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入DB / 商品DB UI の定数・ヘルパー・補助クラス。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QLabel, QFileDialog, QStyledItemDelegate,
)
from PySide6.QtGui import QDrag, QPixmap, QDesktopServices, QCursor

from database.product_db import ProductDatabase

try:
    from utils._desktop_import_compat import is_amazon_sales_channel
except ImportError:
    from desktop.utils._desktop_import_compat import is_amazon_sales_channel  # type: ignore

# 仕入DBでステータスが「販売中」のときの既定ステータス理由（在庫・価格改定CSV連動）
_PURCHASE_STATUS_REASON_SELLING_INVENTORY_CSV = "在庫CSV連動:"

# 仕入DBテーブルで右寄せ・カンマなし表示にする数値列
_PURCHASE_RIGHT_ALIGN_NUMERIC_HEADERS = frozenset({
    "仕入れ個数",
    "仕入れ価格",
    "販売予定価格",
    "見込み利益",
    "損益分岐点",
    "想定利益率",
    "想定ROI",
    "経過日数",
    "TP0",
    "TP1",
    "TP2",
    "TP3",
    "プラットフォーム手数料",
    "Amazon手数料",
    "出荷費用",
    "費用合計",
    "在庫保管手数料",
})


def _purchase_numeric_cell_text(header: str, value: Any) -> str:
    """仕入DBテーブル用の数値表示（カンマ区切りなし）。"""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    text = raw.replace(",", "")
    if header in ("想定利益率", "想定ROI"):
        try:
            return f"{float(text):.2f}"
        except (ValueError, TypeError):
            return ""
    if header == "仕入れ個数":
        try:
            return str(int(round(float(text))))
        except (ValueError, TypeError):
            return raw
    try:
        return str(int(round(float(text))))
    except (ValueError, TypeError):
        return raw


def _make_purchase_numeric_table_item(header: str, value: Any) -> QTableWidgetItem:
    item = QTableWidgetItem(_purchase_numeric_cell_text(header, value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item

# 仕入DB検索：ステータス複数選択（表示ラベル, 内部コード）— テーブル内コンボと同一順
_PURCHASE_STATUS_FILTER_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("出品可能", "ready"),
    ("破損", "damaged"),
    ("登録不可", "unlistable"),
    ("保管中", "storage"),
    ("次回出品予定", "pending"),
    ("販売中", "selling"),
    ("一部販売済み", "partially_sold"),
    ("販売済み", "sold"),
    ("在庫専用", "inventory_only"),
)

# 仕入DB検索：販売チャネル・発送方法（表示ラベル, 内部コード）
_PURCHASE_CHANNEL_FILTER_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("Amazon自己発送", "amazon_mfn"),
    ("フリマ等", "non_amazon"),
)


def _purchase_record_sales_channel(record: Dict[str, Any]) -> str:
    return str(
        record.get("販売チャネル")
        or record.get("sales_channel")
        or ""
    ).strip()


def _purchase_record_shipping_method(record: Dict[str, Any]) -> str:
    return str(
        record.get("発送方法")
        or record.get("shippingMethod")
        or record.get("shipping_method")
        or ""
    ).strip()


def purchase_record_matches_amazon_mfn_filter(record: Dict[str, Any]) -> bool:
    """販売チャネルが Amazon かつ発送方法が自己発送。"""
    if not is_amazon_sales_channel(_purchase_record_sales_channel(record)):
        return False
    return _purchase_record_shipping_method(record) == "自己発送"


def purchase_record_matches_non_amazon_channel_filter(record: Dict[str, Any]) -> bool:
    """販売チャネルが Amazon 以外（メルカリ・ヤフオク等）。"""
    channel = _purchase_record_sales_channel(record)
    if not channel:
        return False
    return not is_amazon_sales_channel(channel)

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


class PurchaseFullTextItemDelegate(QStyledItemDelegate):
    """パス/URL列を ... 省略せず、UserRole のフル値で描画する。"""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideNone
        full = index.data(Qt.ItemDataRole.UserRole)
        if full is not None and str(full).strip():
            option.text = str(full).strip()


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
                image_path = (item.data(Qt.UserRole) or item.text() or "").strip()
                if image_path:
                    # ドラッグデータを作成
                    drag = QDrag(self)
                    mime_data = QMimeData()
                    # テキストデータとして画像名を設定
                    mime_data.setText(image_path)
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
        # JANコードの.0を削除（表示用の正規化）
        jan_value = self.product.get("jan") or ""
        if jan_value:
            jan_str = str(jan_value).strip()
            # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
            if jan_str.endswith(".0"):
                jan_str = jan_str[:-2]
        else:
            jan_str = ""
        self.jan_edit.setText(jan_str)
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

        # JANコードの.0を削除（保存用の正規化）
        jan_text = self.jan_edit.text().strip()
        if jan_text:
            # .0で終わる場合は削除（例: 4970381506544.0 → 4970381506544）
            if jan_text.endswith(".0"):
                jan_text = jan_text[:-2]
            # 数字以外の文字を除去（念のため）
            jan_text = ''.join(c for c in jan_text if c.isdigit())
        
        result = {
            "sku": sku,
            "jan": jan_text if jan_text else None,
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

# 仕入DB: フルパス／URL を UserRole に保持する列
_PURCHASE_FILE_PATH_COLUMNS = frozenset({
    "レシート画像", "保証書画像",
    "画像1", "画像2", "画像3", "画像4", "画像5", "画像6",
})
_PURCHASE_URL_COLUMNS = frozenset({
    "レシート画像URL",
    "画像URL1", "画像URL2", "画像URL3", "画像URL4", "画像URL5", "画像URL6",
})
_PURCHASE_FULLTEXT_MIN_COLUMN_WIDTH = 320


def _purchase_table_cell_full_text(
    header: str,
    item: Optional[QTableWidgetItem],
    fallback: str = "",
) -> str:
    """セル表示が切れていても UserRole のフル値を優先して返す。"""
    if item is None:
        return fallback
    if header in _PURCHASE_FILE_PATH_COLUMNS or header in _PURCHASE_URL_COLUMNS:
        full = item.data(Qt.UserRole)
        if full is not None and str(full).strip():
            return str(full).strip()
    return fallback if fallback else item.text()
