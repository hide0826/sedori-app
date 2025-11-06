#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レシート管理ウィジェット

- 画像アップロード
- OCR結果表示
- マッチング候補表示・修正
- 学習機能
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
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox
)
from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QPixmap

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.receipt_service import ReceiptService
from services.receipt_matching_service import ReceiptMatchingService
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase


class ReceiptOCRThread(QThread):
    """OCR処理をバックグラウンドで実行するスレッド"""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, receipt_service: ReceiptService, image_path: str):
        super().__init__()
        self.receipt_service = receipt_service
        self.image_path = image_path
    
    def run(self):
        try:
            result = self.receipt_service.process_receipt(self.image_path)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ReceiptWidget(QWidget):
    """レシート管理ウィジェット"""
    
    def __init__(self, api_client=None, inventory_widget=None):
        super().__init__()
        self.api_client = api_client
        self.inventory_widget = inventory_widget
        self.receipt_service = ReceiptService()
        self.matching_service = ReceiptMatchingService()
        self.receipt_db = ReceiptDatabase()
        self.inventory_db = InventoryDatabase()
        self.current_receipt_id = None
        self.current_receipt_data = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """UIの設定"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 上部：画像アップロード
        self.setup_upload_section()
        
        # 中央：OCR結果・マッチング候補
        self.setup_result_section()
        
        # 下部：レシート一覧
        self.setup_receipt_list()
    
    def setup_upload_section(self):
        """画像アップロードセクション"""
        upload_group = QGroupBox("レシート画像アップロード")
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
        
        layout.addWidget(upload_group)
    
    def setup_result_section(self):
        """OCR結果・マッチング候補セクション"""
        result_group = QGroupBox("OCR結果・マッチング候補")
        result_layout = QVBoxLayout(result_group)
        
        # OCR結果表示
        ocr_layout = QHBoxLayout()
        ocr_layout.addWidget(QLabel("日付:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        ocr_layout.addWidget(self.date_edit)
        
        ocr_layout.addWidget(QLabel("店舗名（生）:"))
        self.store_name_edit = QLineEdit()
        ocr_layout.addWidget(self.store_name_edit)
        
        ocr_layout.addWidget(QLabel("合計:"))
        self.total_edit = QLineEdit()
        ocr_layout.addWidget(self.total_edit)
        
        ocr_layout.addWidget(QLabel("値引:"))
        self.discount_edit = QLineEdit()
        ocr_layout.addWidget(self.discount_edit)
        result_layout.addLayout(ocr_layout)
        
        # マッチング候補
        match_layout = QHBoxLayout()
        match_layout.addWidget(QLabel("店舗コード:"))
        self.store_code_combo = QComboBox()
        self.store_code_combo.setEditable(True)
        match_layout.addWidget(self.store_code_combo)
        
        self.match_btn = QPushButton("マッチング実行")
        self.match_btn.clicked.connect(self.run_matching)
        self.match_btn.setEnabled(False)
        match_layout.addWidget(self.match_btn)
        result_layout.addLayout(match_layout)
        
        # マッチング結果表示
        self.match_result_label = QLabel("")
        result_layout.addWidget(self.match_result_label)
        
        # 確定ボタン
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("確定")
        self.confirm_btn.clicked.connect(self.confirm_receipt)
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
        
        layout.addWidget(result_group)
    
    def setup_receipt_list(self):
        """レシート一覧セクション"""
        list_group = QGroupBox("レシート一覧")
        list_layout = QVBoxLayout(list_group)
        
        self.receipt_table = QTableWidget()
        self.receipt_table.setColumnCount(6)
        self.receipt_table.setHorizontalHeaderLabels([
            "ID", "日付", "店舗名", "合計", "値引", "店舗コード"
        ])
        self.receipt_table.horizontalHeader().setStretchLastSection(True)
        self.receipt_table.itemDoubleClicked.connect(self.load_receipt)
        list_layout.addWidget(self.receipt_table)
        
        layout.addWidget(list_group)
        self.refresh_receipt_list()
    
    def select_image(self):
        """画像ファイルを選択"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "レシート画像を選択",
            "",
            "画像ファイル (*.jpg *.jpeg *.png *.bmp)"
        )
        if file_path:
            self.image_path_label.setText(f"選択: {Path(file_path).name}")
            self.process_image(file_path)
    
    def process_image(self, image_path: str):
        """画像を処理（OCR実行）"""
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("処理中...")
        
        self.ocr_thread = ReceiptOCRThread(self.receipt_service, image_path)
        self.ocr_thread.finished.connect(self.on_ocr_finished)
        self.ocr_thread.error.connect(self.on_ocr_error)
        self.ocr_thread.start()
    
    def on_ocr_finished(self, result: Dict[str, Any]):
        """OCR完了時の処理"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("画像を選択")
        
        self.current_receipt_id = result.get('id')
        self.current_receipt_data = result
        
        # OCR結果を表示
        purchase_date = result.get('purchase_date')
        if purchase_date:
            try:
                date = QDate.fromString(purchase_date, "yyyy-MM-dd")
                self.date_edit.setDate(date)
            except Exception:
                pass
        
        self.store_name_edit.setText(result.get('store_name_raw') or "")
        self.total_edit.setText(str(result.get('total_amount') or ""))
        self.discount_edit.setText(str(result.get('discount_amount') or ""))
        
        # 店舗コード候補を読み込み
        self.load_store_codes()
        
        self.match_btn.setEnabled(True)
        QMessageBox.information(self, "OCR完了", "レシート情報を抽出しました。")
    
    def on_ocr_error(self, error_msg: str):
        """OCRエラー時の処理"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("画像を選択")
        QMessageBox.critical(self, "OCRエラー", f"OCR処理に失敗しました:\n{error_msg}")
    
    def load_store_codes(self):
        """店舗コード候補を読み込み"""
        self.store_code_combo.clear()
        # 店舗マスタから読み込み（簡易実装）
        from database.store_db import StoreDatabase
        store_db = StoreDatabase()
        stores = store_db.get_all_stores()
        for store in stores:
            code = store.get('supplier_code')
            name = store.get('store_name')
            if code:
                self.store_code_combo.addItem(f"{code} - {name}", code)
    
    def run_matching(self):
        """マッチングを実行"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        # 仕入管理データを取得
        if not self.inventory_widget:
            QMessageBox.warning(self, "警告", "仕入管理データがありません。")
            return
        
        # 仕入管理データを取得（DataFrame形式）
        if hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
            inventory_data = self.inventory_widget.inventory_data
            if hasattr(inventory_data, 'to_dict'):
                inventory_list = inventory_data.to_dict('records')
            else:
                inventory_list = inventory_data if isinstance(inventory_data, list) else []
        else:
            inventory_list = []
        
        if not inventory_list:
            QMessageBox.warning(self, "警告", "仕入管理にデータがありません。")
            return
        
        # マッチング実行
        candidates = self.matching_service.find_match_candidates(
            self.current_receipt_data,
            inventory_list,
            preferred_store_code=self.store_code_combo.currentData(),
        )
        
        if candidates:
            candidate = candidates[0]
            diff = candidate.diff
            if diff is not None and diff <= 10:
                self.match_result_label.setText(
                    f"マッチ成功: 差額 {diff}円（許容範囲内）\n"
                    f"店舗コード: {candidate.store_code}\n"
                    f"アイテム数: {candidate.items_count}"
                )
                self.confirm_btn.setEnabled(True)
            else:
                self.match_result_label.setText(
                    f"マッチ候補あり（差額: {diff}円）\n"
                    f"確認してください。"
                )
                self.confirm_btn.setEnabled(True)
        else:
            self.match_result_label.setText("マッチする候補が見つかりませんでした。")
            self.confirm_btn.setEnabled(True)
    
    def confirm_receipt(self):
        """レシートを確定（学習も実行）"""
        if not self.current_receipt_id:
            return
        
        store_code = self.store_code_combo.currentData()
        if store_code:
            # 学習
            self.matching_service.learn_store_correction(self.current_receipt_id, store_code)
            QMessageBox.information(self, "確定", "レシートを確定し、学習データを更新しました。")
        else:
            QMessageBox.warning(self, "警告", "店舗コードを選択してください。")
        
        self.refresh_receipt_list()
        self.reset_form()
    
    def reset_form(self):
        """フォームをリセット"""
        self.current_receipt_id = None
        self.current_receipt_data = None
        self.date_edit.setDate(QDate.currentDate())
        self.store_name_edit.clear()
        self.total_edit.clear()
        self.discount_edit.clear()
        self.store_code_combo.clear()
        self.match_result_label.clear()
        self.confirm_btn.setEnabled(False)
        self.match_btn.setEnabled(False)
    
    def refresh_receipt_list(self):
        """レシート一覧を更新"""
        receipts = self.receipt_db.find_by_date_and_store(None)
        self.receipt_table.setRowCount(len(receipts))
        
        for row, receipt in enumerate(receipts):
            self.receipt_table.setItem(row, 0, QTableWidgetItem(str(receipt.get('id'))))
            self.receipt_table.setItem(row, 1, QTableWidgetItem(receipt.get('purchase_date') or ""))
            self.receipt_table.setItem(row, 2, QTableWidgetItem(receipt.get('store_name_raw') or ""))
            self.receipt_table.setItem(row, 3, QTableWidgetItem(str(receipt.get('total_amount') or "")))
            self.receipt_table.setItem(row, 4, QTableWidgetItem(str(receipt.get('discount_amount') or "")))
            self.receipt_table.setItem(row, 5, QTableWidgetItem(receipt.get('store_code') or ""))
    
    def load_receipt(self, item: QTableWidgetItem):
        """レシートを読み込み"""
        row = item.row()
        receipt_id = int(self.receipt_table.item(row, 0).text())
        receipt = self.receipt_db.get_receipt(receipt_id)
        if receipt:
            self.current_receipt_id = receipt_id
            self.current_receipt_data = dict(receipt)
            
            purchase_date = receipt.get('purchase_date')
            if purchase_date:
                try:
                    date = QDate.fromString(purchase_date, "yyyy-MM-dd")
                    self.date_edit.setDate(date)
                except Exception:
                    pass
            
            self.store_name_edit.setText(receipt.get('store_name_raw') or "")
            self.total_edit.setText(str(receipt.get('total_amount') or ""))
            self.discount_edit.setText(str(receipt.get('discount_amount') or ""))
            
            self.load_store_codes()
            if receipt.get('store_code'):
                idx = self.store_code_combo.findData(receipt.get('store_code'))
                if idx >= 0:
                    self.store_code_combo.setCurrentIndex(idx)
            
            self.match_btn.setEnabled(True)

