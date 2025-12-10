#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保証書管理ウィジェット

- 画像アップロード
- OCR結果表示（商品名抽出）
- SKU候補表示・選択
- 保証期間入力
- 確定（products更新・学習）
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog,
    QSpinBox, QDateEdit
)
from PySide6.QtCore import Qt, QDate, QThread, Signal

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# デスクトップ側servicesを優先
try:
    from services.warranty_service import WarrantyService
except Exception:
    from desktop.services.warranty_service import WarrantyService
from database.warranty_db import WarrantyDatabase
from database.product_db import ProductDatabase
from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state


class WarrantyOCRThread(QThread):
    """保証書OCR処理をバックグラウンドで実行するスレッド"""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, warranty_service: WarrantyService, image_path: str, sku: Optional[str] = None, warranty_period_days: Optional[int] = None):
        super().__init__()
        self.warranty_service = warranty_service
        self.image_path = image_path
        self.sku = sku
        self.warranty_period_days = warranty_period_days
    
    def run(self):
        try:
            result = self.warranty_service.process_warranty(
                self.image_path,
                sku=self.sku,
                warranty_period_days=self.warranty_period_days,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class WarrantyWidget(QWidget):
    """保証書管理ウィジェット"""
    
    def __init__(self, api_client=None):
        super().__init__()
        self.api_client = api_client
        self.warranty_service = WarrantyService()
        self.warranty_db = WarrantyDatabase()
        self.product_db = ProductDatabase()
        self.current_warranty_id = None
        self.current_warranty_data = None
        self.matching_candidates = []
        
        self.setup_ui()

        # テーブルの列幅を復元
        restore_table_header_state(self.warranty_table, "WarrantyWidget/TableState")

    def save_settings(self):
        """ウィジェットの設定（テーブルの列幅など）を保存します。"""
        save_table_header_state(self.warranty_table, "WarrantyWidget/TableState")
    
    def setup_ui(self):
        """UIの設定"""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
        # 上部：画像アップロード
        self.setup_upload_section()
        
        # 中央：OCR結果・SKU候補
        self.setup_result_section()
        
        # 下部：保証書一覧
        self.setup_warranty_list()
    
    def setup_upload_section(self):
        """画像アップロードセクション"""
        upload_group = QGroupBox("保証書画像アップロード")
        upload_layout = QVBoxLayout(upload_group)
        
        btn_layout = QHBoxLayout()
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
        btn_layout.addStretch()
        upload_layout.addLayout(btn_layout)
        
        self.image_path_label = QLabel("画像未選択")
        upload_layout.addWidget(self.image_path_label)
        
        self.layout.addWidget(upload_group)
    
    def setup_result_section(self):
        """OCR結果・SKU候補セクション"""
        result_group = QGroupBox("OCR結果・SKU候補")
        result_layout = QVBoxLayout(result_group)
        
        # OCR結果表示
        ocr_layout = QHBoxLayout()
        ocr_layout.addWidget(QLabel("商品名（OCR）:"))
        self.product_name_edit = QLineEdit()
        self.product_name_edit.setReadOnly(True)
        ocr_layout.addWidget(self.product_name_edit)
        result_layout.addLayout(ocr_layout)
        
        # SKU候補
        sku_layout = QHBoxLayout()
        sku_layout.addWidget(QLabel("SKU候補:"))
        self.sku_combo = QComboBox()
        self.sku_combo.setEditable(True)
        self.sku_combo.currentTextChanged.connect(self.on_sku_changed)
        sku_layout.addWidget(self.sku_combo)
        result_layout.addLayout(sku_layout)
        
        # 保証期間入力
        warranty_layout = QHBoxLayout()
        warranty_layout.addWidget(QLabel("保証期間（日数）:"))
        self.warranty_days_spin = QSpinBox()
        self.warranty_days_spin.setMinimum(1)
        self.warranty_days_spin.setMaximum(3650)
        self.warranty_days_spin.setValue(365)  # デフォルト1年
        warranty_layout.addWidget(self.warranty_days_spin)
        warranty_layout.addStretch()
        result_layout.addLayout(warranty_layout)
        
        # マッチング結果表示
        self.match_result_label = QLabel("")
        result_layout.addWidget(self.match_result_label)
        
        # 確定ボタン
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("確定")
        self.confirm_btn.clicked.connect(self.confirm_warranty)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addStretch()
        result_layout.addLayout(btn_layout)
        
        self.layout.addWidget(result_group)
    
    def setup_warranty_list(self):
        """保証書一覧セクション"""
        list_group = QGroupBox("保証書一覧")
        list_layout = QVBoxLayout(list_group)
        
        self.warranty_table = QTableWidget()
        self.warranty_table.setColumnCount(5)
        self.warranty_table.setHorizontalHeaderLabels([
            "ID", "商品名", "SKU", "信頼度", "作成日"
        ])
        self.warranty_table.horizontalHeader().setStretchLastSection(True)
        self.warranty_table.itemDoubleClicked.connect(self.load_warranty)
        list_layout.addWidget(self.warranty_table)
        
        self.layout.addWidget(list_group)
        self.refresh_warranty_list()
    
    def select_image(self):
        """画像ファイルを選択"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "保証書画像を選択",
            "",
            "画像ファイル (*.jpg *.jpeg *.png *.bmp)"
        )
        if file_path:
            self.image_path_label.setText(f"選択: {Path(file_path).name}")
            self.process_image(file_path)
    
    def process_image(self, image_path: str):
        """画像を処理（OCR実行）"""
        self.last_image_path = image_path  # 確定時に使用
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("処理中...")
        
        self.ocr_thread = WarrantyOCRThread(
            self.warranty_service,
            image_path,
            warranty_period_days=self.warranty_days_spin.value()
        )
        self.ocr_thread.finished.connect(self.on_ocr_finished)
        self.ocr_thread.error.connect(self.on_ocr_error)
        self.ocr_thread.start()
    
    def on_ocr_finished(self, result: Dict[str, Any]):
        """OCR完了時の処理"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("画像を選択")
        
        self.current_warranty_id = result.get('warranty_id')
        self.current_warranty_data = result
        
        # OCR結果を表示
        product_name = result.get('product_name')
        self.product_name_edit.setText(product_name or "")
        
        # SKU候補を読み込み
        matched_sku = result.get('matched_sku')
        if matched_sku:
            self.sku_combo.clear()
            self.sku_combo.addItem(matched_sku, matched_sku)
            self.sku_combo.setCurrentIndex(0)
            self.match_result_label.setText(
                f"マッチ成功: SKU {matched_sku}\n"
                f"信頼度: {result.get('confidence', 0):.2f}"
            )
            self.confirm_btn.setEnabled(True)
        else:
            # マッチしない場合は候補を探す
            if product_name:
                candidates = self.warranty_service.find_matching_products(product_name)
                self.matching_candidates = candidates
                self.sku_combo.clear()
                for candidate in candidates:
                    sku = candidate.get('sku')
                    name = candidate.get('product_name')
                    if sku:
                        self.sku_combo.addItem(f"{sku} - {name}", sku)
                if candidates:
                    self.match_result_label.setText(f"候補が {len(candidates)} 件見つかりました。")
                    self.confirm_btn.setEnabled(True)
                else:
                    self.match_result_label.setText("マッチする商品が見つかりませんでした。SKUを手動で入力してください。")
                    self.confirm_btn.setEnabled(True)
            else:
                self.match_result_label.setText("商品名が抽出できませんでした。")
                self.confirm_btn.setEnabled(False)
        
        QMessageBox.information(self, "OCR完了", "保証書情報を抽出しました。")
    
    def on_ocr_error(self, error_msg: str):
        """OCRエラー時の処理"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("画像を選択")
        QMessageBox.critical(self, "OCRエラー", f"OCR処理に失敗しました:\n{error_msg}")
    
    def on_sku_changed(self, text: str):
        """SKUが変更されたときの処理"""
        # 選択されたSKUの商品情報を表示
        if text:
            sku = text.split(' - ')[0] if ' - ' in text else text
            product = self.product_db.get_by_sku(sku)
            if product:
                self.match_result_label.setText(
                    f"選択中: {product.get('product_name')}\n"
                    f"SKU: {sku}"
                )
            else:
                self.match_result_label.setText(f"SKU {sku} が見つかりません。")
    
    def confirm_warranty(self):
        """保証書を確定（products更新・学習も実行）"""
        if not self.current_warranty_id:
            # 新規処理の場合
            sku = self.sku_combo.currentData() or self.sku_combo.currentText()
            if not sku:
                QMessageBox.warning(self, "警告", "SKUを選択または入力してください。")
                return
            
            product_name = self.product_name_edit.text()
            if not product_name:
                QMessageBox.warning(self, "警告", "商品名がありません。")
                return
            
            # 再処理（SKU指定）
            if hasattr(self, 'last_image_path'):
                self.upload_btn.setEnabled(False)
                self.upload_btn.setText("処理中...")
                
                self.ocr_thread = WarrantyOCRThread(
                    self.warranty_service,
                    self.last_image_path,
                    sku=sku,
                    warranty_period_days=self.warranty_days_spin.value()
                )
                self.ocr_thread.finished.connect(self.on_confirm_finished)
                self.ocr_thread.error.connect(self.on_ocr_error)
                self.ocr_thread.start()
        else:
            # 既存保証書の修正
            sku = self.sku_combo.currentData() or self.sku_combo.currentText()
            if sku:
                self.warranty_service.learn_correction(self.current_warranty_id, sku)
                QMessageBox.information(self, "確定", "保証書を確定し、学習データを更新しました。")
                self.refresh_warranty_list()
                self.reset_form()
    
    def on_confirm_finished(self, result: Dict[str, Any]):
        """確定処理完了時の処理"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("画像を選択")
        
        if result.get('status') == 'matched':
            QMessageBox.information(self, "確定", "保証書を確定し、商品情報を更新しました。")
            self.refresh_warranty_list()
            self.reset_form()
        else:
            QMessageBox.warning(self, "警告", "確定に失敗しました。")
    
    def reset_form(self):
        """フォームをリセット"""
        self.current_warranty_id = None
        self.current_warranty_data = None
        self.matching_candidates = []
        self.product_name_edit.clear()
        self.sku_combo.clear()
        self.warranty_days_spin.setValue(365)
        self.match_result_label.clear()
        self.confirm_btn.setEnabled(False)
        if hasattr(self, 'last_image_path'):
            delattr(self, 'last_image_path')
    
    def refresh_warranty_list(self):
        """保証書一覧を更新"""
        warranties = self.warranty_db.list_all()
        self.warranty_table.setRowCount(len(warranties))
        
        for row, warranty in enumerate(warranties):
            self.warranty_table.setItem(row, 0, QTableWidgetItem(str(warranty.get('id'))))
            self.warranty_table.setItem(row, 1, QTableWidgetItem(warranty.get('ocr_product_name') or ""))
            self.warranty_table.setItem(row, 2, QTableWidgetItem(warranty.get('sku') or ""))
            confidence = warranty.get('matched_confidence')
            conf_text = f"{confidence:.2f}" if confidence is not None else ""
            self.warranty_table.setItem(row, 3, QTableWidgetItem(conf_text))
            created_at = warranty.get('created_at')
            if created_at:
                # 日時文字列から日付部分のみ抽出
                date_str = str(created_at).split()[0] if ' ' in str(created_at) else str(created_at)
                self.warranty_table.setItem(row, 4, QTableWidgetItem(date_str))
            else:
                self.warranty_table.setItem(row, 4, QTableWidgetItem(""))
    
    def load_warranty(self, item: QTableWidgetItem):
        """保証書を読み込み"""
        row = item.row()
        warranty_id = int(self.warranty_table.item(row, 0).text())
        warranty = self.warranty_db.get_warranty(warranty_id)
        if warranty:
            self.current_warranty_id = warranty_id
            self.current_warranty_data = dict(warranty)
            
            self.product_name_edit.setText(warranty.get('ocr_product_name') or "")
            
            sku = warranty.get('sku')
            if sku:
                self.sku_combo.clear()
                product = self.product_db.get_by_sku(sku)
                if product:
                    self.sku_combo.addItem(f"{sku} - {product.get('product_name')}", sku)
                else:
                    self.sku_combo.addItem(sku, sku)
                self.sku_combo.setCurrentIndex(0)
            
            self.confirm_btn.setEnabled(True)

