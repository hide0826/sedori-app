#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品データベース閲覧・編集ウィジェット
"""
from __future__ import annotations

import sys
import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QGroupBox, QFormLayout, QLineEdit, QDialog, QDialogButtonBox,
    QMessageBox, QLabel
)

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from database.product_db import ProductDatabase


class ProductEditDialog(QDialog):
    """商品情報の編集ダイアログ"""

    def __init__(self, parent=None, product: Optional[dict] = None):
        super().__init__(parent)
        self.product = product or {}
        self.db = ProductDatabase()
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

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

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

        return {
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


class ProductWidget(QWidget):
    """商品データ閲覧・編集タブ"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = ProductDatabase()
        self.setup_ui()
        self.load_products()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QLabel("商品データベース")
        header.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(header)

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
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "SKU", "商品名", "JAN", "ASIN", "仕入日", "仕入価格",
            "数量", "店舗コード", "店舗名", "保証期間(日)", "保証満了日"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

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

