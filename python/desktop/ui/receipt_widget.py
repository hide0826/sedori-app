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
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea
)
from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QPixmap

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# デスクトップ側servicesを優先して読み込む
try:
    from services.receipt_service import ReceiptService  # python/desktop/services
    from services.receipt_matching_service import ReceiptMatchingService
except Exception:
    # 明示的パス指定のフォールバック
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
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
        self.product_widget = None  # ProductWidgetへの参照
        self.receipt_service = ReceiptService()
        self.matching_service = ReceiptMatchingService()
        self.receipt_db = ReceiptDatabase()
        self.inventory_db = InventoryDatabase()
        self.current_receipt_id = None
        self.current_receipt_data = None
        
        self.setup_ui()
    
    def set_product_widget(self, product_widget):
        """ProductWidgetへの参照を設定"""
        self.product_widget = product_widget
    
    def setup_ui(self):
        """UIの設定"""
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(10)
        
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
        
        self.layout.addWidget(upload_group)
    
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
        
        ocr_layout.addWidget(QLabel("電話番号:"))
        self.phone_edit = QLineEdit()
        ocr_layout.addWidget(self.phone_edit)
        
        ocr_layout.addWidget(QLabel("合計:"))
        self.total_edit = QLineEdit()
        ocr_layout.addWidget(self.total_edit)
        
        ocr_layout.addWidget(QLabel("値引:"))
        self.discount_edit = QLineEdit()
        ocr_layout.addWidget(self.discount_edit)
        
        ocr_layout.addWidget(QLabel("点数:"))
        self.items_count_edit = QLineEdit()
        ocr_layout.addWidget(self.items_count_edit)
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
        
        self.view_image_btn = QPushButton("画像確認")
        self.view_image_btn.clicked.connect(self.view_receipt_image)
        self.view_image_btn.setEnabled(False)
        match_layout.addWidget(self.view_image_btn)
        
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
        
        self.layout.addWidget(result_group)
    
    def setup_receipt_list(self):
        """レシート一覧セクション"""
        list_group = QGroupBox("レシート一覧")
        list_layout = QVBoxLayout(list_group)
        
        self.receipt_table = QTableWidget()
        self.receipt_table.setColumnCount(9)
        self.receipt_table.setHorizontalHeaderLabels([
            "ID", "レシートID", "日付", "店舗名", "電話番号", "合計", "値引", "点数", "店舗コード"
        ])
        self.receipt_table.horizontalHeader().setStretchLastSection(True)
        self.receipt_table.itemDoubleClicked.connect(self.load_receipt)
        list_layout.addWidget(self.receipt_table)
        
        self.layout.addWidget(list_group)
        self.refresh_receipt_list()
    
    def select_image(self):
        """画像ファイルを選択"""
        # デフォルトディレクトリを設定（暫定的）
        default_dir = r"D:\せどり総合\店舗せどり仕入リスト入れ\仕入帳\20251115八王子ルート\レシート"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "レシート画像を選択",
            default_dir,
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
        self.phone_edit.setText(result.get('phone_number') or "")
        self.total_edit.setText(str(result.get('total_amount') or ""))
        self.discount_edit.setText(str(result.get('discount_amount') or ""))
        items_count = result.get('items_count')
        self.items_count_edit.setText(str(items_count) if items_count is not None else "")
        
        # 店舗コード候補を読み込み
        self.load_store_codes()
        
        # 仕入DBから自動検索・入力
        self.search_from_purchase_db()
        
        self.match_btn.setEnabled(True)
        self.view_image_btn.setEnabled(True)
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
        stores = store_db.list_stores()
        for store in stores:
            code = store.get('supplier_code')
            name = store.get('store_name')
            if code:
                self.store_code_combo.addItem(f"{code} - {name}", code)
    
    def search_from_purchase_db(self):
        """仕入DBから日付・店舗名・電話番号で検索して店舗コードと点数を自動入力"""
        if not self.product_widget:
            return
        
        # OCR結果から日付・店舗名・電話番号を取得
        purchase_date = self.date_edit.date().toString("yyyy-MM-dd")
        store_name_raw = self.store_name_edit.text().strip()
        phone_number = self.phone_edit.text().strip()
        
        if not purchase_date or not store_name_raw:
            return
        
        # 仕入DBの全データを取得
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            return
        
        # 店舗マスタから電話番号で店舗を検索
        from database.store_db import StoreDatabase
        store_db = StoreDatabase()
        stores = store_db.list_stores()
        
        # 電話番号で店舗を検索（部分一致）
        matched_store_code = None
        if phone_number:
            for store in stores:
                store_phone = store.get('phone') or ''
                if store_phone and (phone_number in store_phone or store_phone in phone_number):
                    matched_store_code = store.get('supplier_code')
                    break
        
        # 店舗名でも検索（電話番号で見つからない場合）
        if not matched_store_code:
            for store in stores:
                store_name = store.get('store_name') or ''
                # 店舗名の部分一致チェック
                if store_name and store_name_raw and (store_name_raw in store_name or store_name in store_name_raw):
                    matched_store_code = store.get('supplier_code')
                    break
        
        if not matched_store_code:
            return
        
        # 日付を正規化（yyyy-MM-dd形式）
        normalized_date = purchase_date.replace('/', '-')
        if ' ' in normalized_date:
            normalized_date = normalized_date.split(' ')[0]
        
        # 仕入DBから該当日付・店舗コードで検索
        matched_records = []
        for record in purchase_records:
            record_date = record.get('仕入れ日') or record.get('purchase_date') or ''
            record_store_code = record.get('仕入先') or record.get('store_code') or ''
            
            # 日付の正規化
            normalized_record_date = record_date.replace('/', '-')
            if ' ' in normalized_record_date:
                normalized_record_date = normalized_record_date.split(' ')[0]
            
            # 日付と店舗コードでマッチング
            if normalized_record_date.startswith(normalized_date) and record_store_code == matched_store_code:
                matched_records.append(record)
        
        if matched_records:
            # 店舗コードを入力
            idx = self.store_code_combo.findData(matched_store_code)
            if idx >= 0:
                self.store_code_combo.setCurrentIndex(idx)
            
            # 仕入れ点数を集計
            total_items = 0
            for record in matched_records:
                quantity = record.get('仕入れ個数') or record.get('quantity') or 0
                try:
                    total_items += int(quantity)
                except (ValueError, TypeError):
                    pass
            
            # 点数欄に入力
            if total_items > 0:
                self.items_count_edit.setText(str(total_items))
    
    def run_matching(self):
        """マッチングを実行"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        # 仕入DBデータを取得
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return
        
        # 仕入DBの全データを取得
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        if not purchase_records:
            QMessageBox.warning(self, "警告", "仕入DBにデータがありません。")
            return
        
        # マッチング実行
        candidates = self.matching_service.find_match_candidates(
            self.current_receipt_data,
            purchase_records,
            preferred_store_code=self.store_code_combo.currentData(),
        )
        
        if candidates:
            candidate = candidates[0]
            diff = candidate.diff
            
            # マッチング結果の点数を点数欄に入力
            if candidate.items_count > 0:
                self.items_count_edit.setText(str(candidate.items_count))
                # current_receipt_dataにも反映
                if self.current_receipt_data:
                    self.current_receipt_data['items_count'] = candidate.items_count
            
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
        if not store_code:
            QMessageBox.warning(self, "警告", "店舗コードを選択してください。")
            return
        
        # 日付を取得
        purchase_date = self.date_edit.date().toString("yyyy-MM-dd")
        if not purchase_date:
            QMessageBox.warning(self, "警告", "日付が設定されていません。")
            return
        
        # レシートIDを生成
        receipt_id_str = self.receipt_db.generate_receipt_id(purchase_date, store_code)
        
        # 同名のレシートIDが存在するか確認
        existing_receipt = self.receipt_db.find_by_receipt_id(receipt_id_str)
        if existing_receipt:
            reply = QMessageBox.question(
                self, "確認",
                f"レシートID「{receipt_id_str}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # 点数を取得
        items_count_text = self.items_count_edit.text().strip()
        items_count = None
        if items_count_text:
            try:
                items_count = int(items_count_text)
            except ValueError:
                pass
        
        # 現在の画像パスを取得
        current_receipt = self.receipt_db.get_receipt(self.current_receipt_id)
        if not current_receipt:
            QMessageBox.warning(self, "警告", "レシートデータが見つかりません。")
            return
        
        old_image_path = current_receipt.get('file_path')
        if not old_image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # 新しい画像ファイル名を生成
        from pathlib import Path
        old_image_file = Path(old_image_path)
        new_image_name = f"{receipt_id_str}{old_image_file.suffix}"
        new_image_path = old_image_file.parent / new_image_name
        
        # 同名ファイルが存在する場合の確認
        if new_image_path.exists() and str(new_image_path) != str(old_image_file):
            reply = QMessageBox.question(
                self, "確認",
                f"画像ファイル「{new_image_name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # 画像ファイルをリネーム
        try:
            if str(new_image_path) != str(old_image_file):
                import shutil
                shutil.move(str(old_image_file), str(new_image_path))
        except Exception as e:
            QMessageBox.warning(self, "警告", f"画像ファイルのリネームに失敗しました:\n{e}")
            return
        
        # レシートDBを更新（店舗コード、点数、レシートID、画像パス）
        updates = {
            "store_code": store_code,
            "receipt_id": receipt_id_str,
            "file_path": str(new_image_path)
        }
        if items_count is not None:
            updates["items_count"] = items_count
        
        self.receipt_db.update_receipt(self.current_receipt_id, updates)
        
        # 学習
        self.matching_service.learn_store_correction(self.current_receipt_id, store_code)
        QMessageBox.information(
            self, "確定",
            f"レシートを確定しました。\nレシートID: {receipt_id_str}\n画像ファイル: {new_image_name}"
        )
        
        self.refresh_receipt_list()
        self.reset_form()
    
    def reset_form(self):
        """フォームをリセット"""
        self.current_receipt_id = None
        self.current_receipt_data = None
        self.date_edit.setDate(QDate.currentDate())
        self.store_name_edit.clear()
        self.phone_edit.clear()
        self.total_edit.clear()
        self.discount_edit.clear()
        self.items_count_edit.clear()
        self.store_code_combo.clear()
        self.match_result_label.clear()
        self.confirm_btn.setEnabled(False)
        self.match_btn.setEnabled(False)
        self.view_image_btn.setEnabled(False)
    
    def refresh_receipt_list(self):
        """レシート一覧を更新"""
        receipts = self.receipt_db.find_by_date_and_store(None)
        self.receipt_table.setRowCount(len(receipts))
        
        for row, receipt in enumerate(receipts):
            self.receipt_table.setItem(row, 0, QTableWidgetItem(str(receipt.get('id'))))
            self.receipt_table.setItem(row, 1, QTableWidgetItem(receipt.get('receipt_id') or ""))
            self.receipt_table.setItem(row, 2, QTableWidgetItem(receipt.get('purchase_date') or ""))
            self.receipt_table.setItem(row, 3, QTableWidgetItem(receipt.get('store_name_raw') or ""))
            self.receipt_table.setItem(row, 4, QTableWidgetItem(receipt.get('phone_number') or ""))
            self.receipt_table.setItem(row, 5, QTableWidgetItem(str(receipt.get('total_amount') or "")))
            self.receipt_table.setItem(row, 6, QTableWidgetItem(str(receipt.get('discount_amount') or "")))
            self.receipt_table.setItem(row, 7, QTableWidgetItem(str(receipt.get('items_count') or "")))
            self.receipt_table.setItem(row, 8, QTableWidgetItem(receipt.get('store_code') or ""))
    
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
            self.phone_edit.setText(receipt.get('phone_number') or "")
            self.total_edit.setText(str(receipt.get('total_amount') or ""))
            self.discount_edit.setText(str(receipt.get('discount_amount') or ""))
            items_count = receipt.get('items_count')
            self.items_count_edit.setText(str(items_count) if items_count is not None else "")
            
            self.load_store_codes()
            if receipt.get('store_code'):
                idx = self.store_code_combo.findData(receipt.get('store_code'))
                if idx >= 0:
                    self.store_code_combo.setCurrentIndex(idx)
            
            # 仕入DBから自動検索・入力（店舗コードが未設定の場合）
            if not receipt.get('store_code'):
                self.search_from_purchase_db()
            
            self.match_btn.setEnabled(True)
            self.view_image_btn.setEnabled(True)
    
    def view_receipt_image(self):
        """レシート画像を別画面で表示"""
        if not self.current_receipt_data:
            QMessageBox.warning(self, "警告", "レシートデータがありません。")
            return
        
        # 画像パスを取得
        image_path = None
        
        # current_receipt_dataから取得を試みる
        if self.current_receipt_data:
            image_path = self.current_receipt_data.get('file_path')
        
        # レシートIDがある場合はDBから取得
        if not image_path and self.current_receipt_id:
            receipt = self.receipt_db.get_receipt(self.current_receipt_id)
            if receipt:
                image_path = receipt.get('file_path')
        
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルが見つかりません。")
            return
        
        # ファイルの存在確認
        from pathlib import Path
        image_file = Path(image_path)
        if not image_file.exists():
            QMessageBox.warning(self, "警告", f"画像ファイルが存在しません:\n{image_path}")
            return
        
        # 画像表示ダイアログを作成
        dialog = QDialog(self)
        dialog.setWindowTitle("レシート画像")
        
        # 画像サイズを取得
        pixmap = QPixmap(str(image_file))
        original_width = pixmap.width()
        original_height = pixmap.height()
        
        # 画面サイズを取得して、適切なウィンドウサイズを設定
        screen = dialog.screen().availableGeometry()
        max_dialog_width = int(screen.width() * 0.9)  # 画面幅の90%
        max_dialog_height = int(screen.height() * 0.9)  # 画面高さの90%
        
        # 画像を画面サイズに合わせて縮小（アスペクト比を保持）
        if original_width > max_dialog_width or original_height > max_dialog_height:
            scaled_pixmap = pixmap.scaled(
                max_dialog_width, max_dialog_height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            # 画像が小さい場合は元のサイズで表示
            scaled_pixmap = pixmap
        
        # ダイアログサイズを画像サイズに合わせる（ただし最大サイズは制限）
        dialog_width = min(scaled_pixmap.width() + 40, max_dialog_width)
        dialog_height = min(scaled_pixmap.height() + 100, max_dialog_height)  # ボタン分の余白を追加
        
        dialog.setMinimumSize(dialog_width, dialog_height)
        dialog.resize(dialog_width, dialog_height)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # スクロールエリアを作成
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setAlignment(Qt.AlignCenter)
        scroll_area.setMinimumSize(scaled_pixmap.width(), scaled_pixmap.height())
        
        # 画像ラベルを作成
        image_label = QLabel()
        image_label.setPixmap(scaled_pixmap)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumSize(scaled_pixmap.width(), scaled_pixmap.height())
        
        scroll_area.setWidget(image_label)
        layout.addWidget(scroll_area)
        
        # 画像情報ラベル（元のサイズを表示）
        info_label = QLabel(f"画像サイズ: {original_width} x {original_height} px")
        info_label.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(info_label)
        
        # 閉じるボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.close)
        layout.addWidget(button_box)
        
        dialog.exec()

