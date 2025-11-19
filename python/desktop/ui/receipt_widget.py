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
        
        ocr_layout.addWidget(QLabel("時刻:"))
        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText("HH:MM")
        self.time_edit.setMaximumWidth(80)
        ocr_layout.addWidget(self.time_edit)
        
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
        
        # 時刻を表示
        purchase_time = result.get('purchase_time')
        self.time_edit.setText(purchase_time or "")
        
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
        
        # レシートIDを生成（カスタムID、表示用）
        receipt_id_str = self.receipt_db.generate_receipt_id(purchase_date, store_code)
        
        # 同名のレシートIDが存在するか確認
        existing_receipt = self.receipt_db.find_by_receipt_id(receipt_id_str)
        if existing_receipt and existing_receipt.get('id') != self.current_receipt_id:
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
        original_file_path = current_receipt.get('original_file_path')  # 元のファイルパス
        if not old_image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        # 新しい画像ファイル名を生成
        from pathlib import Path
        import os
        import traceback
        from datetime import datetime
        
        # デバッグログ出力先
        log_path = Path(__file__).resolve().parents[1] / "desktop_error.log"
        
        def _write_log(message: str):
            """デバッグログを書き込む"""
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] レシートリネーム処理\n")
                    f.write(f"{message}\n")
                    f.write("-" * 80 + "\n")
            except Exception:
                pass
        
        # DBのID（receipt_id）を取得（ファイル名に使用）
        db_receipt_id = self.current_receipt_id
        
        _write_log(f"開始: レシートID（カスタム）={receipt_id_str}, DB ID={db_receipt_id}, コピー先パス={old_image_path}, 元のパス={original_file_path}")
        
        # コピー先ファイルのパスを絶対パスに正規化
        old_image_file = Path(old_image_path)
        _write_log(f"コピー先パス解析: is_absolute={old_image_file.is_absolute()}, パス={old_image_file}")
        
        if not old_image_file.is_absolute():
            # 相対パスの場合は現在の作業ディレクトリから解決を試みる
            old_image_file = Path(os.path.abspath(old_image_path))
            _write_log(f"絶対パス変換後: {old_image_file}")
        
        # 元のファイルパスを取得（リネーム対象）
        original_file = None
        if original_file_path:
            original_file = Path(original_file_path)
            if not original_file.is_absolute():
                original_file = Path(os.path.abspath(original_file_path))
            _write_log(f"元のファイルパス: {original_file}, 存在={original_file.exists() if original_file else False}")
        
        # コピー先ファイルの存在確認
        file_exists = old_image_file.exists()
        _write_log(f"コピー先ファイル存在確認: {file_exists}, パス={old_image_file}")
        
        if not file_exists:
            error_msg = (
                f"画像ファイルが見つかりません:\n{old_image_file}\n\n"
                f"元のパス: {old_image_path}"
            )
            _write_log(f"エラー: {error_msg}")
            QMessageBox.warning(self, "警告", error_msg)
            return
        
        # 新しいファイル名を生成: {YYYYMMDD}_{store_code}_{receipt_id}.{拡張子}
        date_str = purchase_date.replace("-", "") if purchase_date else "UNKNOWN"
        if len(date_str) == 10:  # yyyy-MM-dd形式
            date_str = date_str[:4] + date_str[5:7] + date_str[8:10]
        elif len(date_str) != 8:
            date_str = "UNKNOWN"
        
        new_image_name = f"{date_str}_{store_code}_{db_receipt_id}{old_image_file.suffix}"
        new_image_path = old_image_file.parent / new_image_name
        
        # 元のファイルの新しいパスも生成
        new_original_path = None
        if original_file and original_file.exists():
            new_original_path = original_file.parent / f"{date_str}_{store_code}_{db_receipt_id}{original_file.suffix}"
            _write_log(f"元のファイルの新しいパス: {new_original_path}")
        
        _write_log(f"新しいファイル名生成: {new_image_name}, コピー先パス={new_image_path}")
        
        # 同名ファイルが存在する場合の確認（自分自身でない場合のみ）
        if new_image_path.exists() and new_image_path != old_image_file:
            _write_log(f"同名ファイル存在: {new_image_path}")
            reply = QMessageBox.question(
                self, "確認",
                f"画像ファイル「{new_image_name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _write_log("ユーザーが上書きをキャンセル")
                return
        
        # 元のファイルも同名ファイルが存在する場合の確認
        if new_original_path and new_original_path.exists() and new_original_path != original_file:
            _write_log(f"元のファイルの同名ファイル存在: {new_original_path}")
            reply = QMessageBox.question(
                self, "確認",
                f"元の画像ファイル「{new_original_path.name}」は既に存在します。\n上書きしますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                _write_log("ユーザーが元のファイルの上書きをキャンセル")
                return
        
        # コピー先ファイルをリネーム（ファイル名が変更される場合のみ）
        if new_image_path != old_image_file:
            _write_log(f"コピー先リネーム実行: {old_image_file} -> {new_image_path}")
            try:
                import shutil
                # ファイルをリネーム（移動）
                _write_log(f"shutil.move実行前: 元ファイル存在={old_image_file.exists()}, 新ファイル存在={new_image_path.exists()}")
                shutil.move(str(old_image_file), str(new_image_path))
                _write_log(f"shutil.move実行後: 元ファイル存在={old_image_file.exists()}, 新ファイル存在={new_image_path.exists()}")
                
                # リネーム後のファイルが存在することを確認
                if not new_image_path.exists():
                    raise Exception(f"リネーム後のファイルが見つかりません: {new_image_path}")
                
                _write_log(f"コピー先リネーム成功: {new_image_path}")
            except Exception as e:
                error_detail = traceback.format_exc()
                _write_log(f"コピー先リネームエラー: {str(e)}\n{error_detail}")
                QMessageBox.critical(
                    self, "エラー",
                    f"画像ファイルのリネームに失敗しました:\n\n"
                    f"エラー: {str(e)}\n\n"
                    f"元のファイル: {old_image_file}\n"
                    f"新しいファイル: {new_image_path}\n\n"
                    f"詳細はログファイルを確認してください:\n{log_path}"
                )
                return
        else:
            _write_log(f"コピー先リネーム不要: ファイル名が同じです（{old_image_file} == {new_image_path}）")
        
        # 元のファイルもリネーム（存在する場合）
        if original_file and original_file.exists() and new_original_path:
            if new_original_path != original_file:
                _write_log(f"元のファイルリネーム実行: {original_file} -> {new_original_path}")
                try:
                    import shutil
                    _write_log(f"元のファイルshutil.move実行前: 元ファイル存在={original_file.exists()}, 新ファイル存在={new_original_path.exists()}")
                    shutil.move(str(original_file), str(new_original_path))
                    _write_log(f"元のファイルshutil.move実行後: 元ファイル存在={original_file.exists()}, 新ファイル存在={new_original_path.exists()}")
                    
                    # リネーム後のファイルが存在することを確認
                    if not new_original_path.exists():
                        raise Exception(f"元のファイルのリネーム後のファイルが見つかりません: {new_original_path}")
                    
                    _write_log(f"元のファイルリネーム成功: {new_original_path}")
                except Exception as e:
                    error_detail = traceback.format_exc()
                    _write_log(f"元のファイルリネームエラー: {str(e)}\n{error_detail}")
                    # 元のファイルのリネーム失敗は警告のみ（コピー先は成功しているため）
                    QMessageBox.warning(
                        self, "警告",
                        f"元の画像ファイルのリネームに失敗しました:\n\n"
                        f"エラー: {str(e)}\n\n"
                        f"元のファイル: {original_file}\n"
                        f"新しいファイル: {new_original_path}\n\n"
                        f"コピー先のリネームは成功しています。"
                    )
            else:
                _write_log(f"元のファイルリネーム不要: ファイル名が同じです（{original_file} == {new_original_path}）")
        
        # レシートDBを更新（店舗コード、点数、レシートID、画像パス）
        # リネームが実行された場合は新しいパス、実行されなかった場合は元のパスを使用
        final_image_path = str(new_image_path) if new_image_path != old_image_file else str(old_image_file)
        final_original_path = str(new_original_path) if (new_original_path and original_file and new_original_path != original_file) else original_file_path
        _write_log(f"DB更新: 最終的なコピー先パス={final_image_path}, 最終的な元のパス={final_original_path}")
        
        # 時刻を取得（HH:MM形式）
        purchase_time = self.time_edit.text().strip()
        # 時刻の形式を検証（HH:MM形式）
        if purchase_time:
            import re
            if not re.match(r"^\d{1,2}:\d{2}$", purchase_time):
                # 形式が正しくない場合は警告（ただし処理は継続）
                QMessageBox.warning(self, "警告", f"時刻の形式が正しくありません（HH:MM形式で入力してください）: {purchase_time}")
                purchase_time = None
        
        updates = {
            "store_code": store_code,
            "receipt_id": receipt_id_str,
            "file_path": final_image_path
        }
        if purchase_time:
            updates["purchase_time"] = purchase_time
        if final_original_path:
            updates["original_file_path"] = final_original_path
        if items_count is not None:
            updates["items_count"] = items_count
        
        _write_log(f"DB更新内容: {updates}")
        update_result = self.receipt_db.update_receipt(self.current_receipt_id, updates)
        _write_log(f"DB更新結果: {update_result}")
        
        # 学習
        self.matching_service.learn_store_correction(self.current_receipt_id, store_code)
        
        # 仕入DBの該当SKUにレシートIDを自動入力
        self._link_receipt_to_purchase_records(
            purchase_date=purchase_date,
            purchase_time=purchase_time,
            store_code=store_code,
            receipt_id_str=receipt_id_str,
            db_receipt_id=db_receipt_id
        )
        
        QMessageBox.information(
            self, "確定",
            f"レシートを確定しました。\nレシートID: {receipt_id_str}\n画像ファイル: {new_image_name}"
        )
        
        self.refresh_receipt_list()
        self.reset_form()
    
    def _link_receipt_to_purchase_records(
        self,
        purchase_date: str,
        purchase_time: Optional[str],
        store_code: str,
        receipt_id_str: str,
        db_receipt_id: int
    ):
        """
        仕入DBの該当SKUにレシートIDを自動入力
        
        Args:
            purchase_date: レシート日付（yyyy-MM-dd形式）
            purchase_time: レシート時刻（HH:MM形式、Noneの場合は時刻比較なし）
            store_code: 店舗コード
            receipt_id_str: レシートID（カスタムID）
            db_receipt_id: レシートDBのID
        """
        from pathlib import Path
        from datetime import datetime
        log_path = Path(__file__).resolve().parents[1] / "desktop_error.log"
        
        def _write_log(message: str):
            """デバッグログを書き込む"""
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] レシートID自動入力処理\n")
                    f.write(f"{message}\n")
                    f.write("-" * 80 + "\n")
            except Exception:
                pass
        
        _write_log(f"開始: 日付={purchase_date}, 時刻={purchase_time}, 店舗コード={store_code}, レシートID={receipt_id_str}, DB ID={db_receipt_id}")
        
        # 仕入管理タブのデータを優先的に使用
        inventory_records = []
        inventory_data_exists = False
        if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
            inventory_data_exists = True
            try:
                import pandas as pd
                inventory_records = self.inventory_widget.inventory_data.fillna("").to_dict(orient="records")
                _write_log(f"仕入管理タブから{len(inventory_records)}件のデータを取得")
            except Exception as e:
                _write_log(f"仕入管理タブのデータ取得エラー: {e}")
        else:
            _write_log(f"仕入管理タブのデータが存在しません: inventory_widget={self.inventory_widget is not None}, hasattr={hasattr(self.inventory_widget, 'inventory_data') if self.inventory_widget else False}, inventory_data={self.inventory_widget.inventory_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') else None}")
        
        # 仕入DBの全データを取得（フォールバック）
        purchase_records = []
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            _write_log(f"仕入DBから{len(purchase_records)}件のデータを取得")
        
        # 仕入管理タブのデータを優先、なければ仕入DBを使用
        if inventory_records:
            target_records = inventory_records
            _write_log("仕入管理タブのデータを使用")
        elif purchase_records:
            target_records = purchase_records
            _write_log("仕入DBのデータを使用")
        else:
            _write_log("データが見つかりません")
            return
        
        # 日付を正規化（yyyy-MM-dd形式）
        normalized_date = purchase_date.replace('/', '-')
        if ' ' in normalized_date:
            normalized_date = normalized_date.split(' ')[0]
        
        # レシート時刻をdatetimeに変換（比較用）
        receipt_datetime = None
        if purchase_time:
            try:
                from datetime import datetime
                time_parts = purchase_time.split(':')
                if len(time_parts) == 2:
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                    receipt_datetime = datetime.strptime(f"{normalized_date} {hour:02d}:{minute:02d}:00", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        
        # ProductDatabaseを取得
        from database.product_db import ProductDatabase
        product_db = ProductDatabase()
        
        matched_count = 0
        updated_count = 0
        
        # 仕入DBから該当するSKUを検索
        matched_skus = []
        for record in target_records:
            # SKUを取得
            sku = record.get('SKU') or record.get('sku') or ''
            if not sku or sku == '未実装':
                continue
            
            # 店舗コードでフィルタリング
            record_store_code = record.get('仕入先') or record.get('store_code') or ''
            if record_store_code != store_code:
                continue
            
            # 日付でフィルタリング
            record_date = record.get('仕入れ日') or record.get('purchase_date') or ''
            if not record_date:
                continue
            
            # 日付の正規化（時刻が含まれている場合も対応）
            normalized_record_date = str(record_date).replace('/', '-')
            record_date_only = normalized_record_date
            if ' ' in normalized_record_date:
                record_date_only = normalized_record_date.split(' ')[0]
            
            # 日付が一致しない場合はスキップ
            if not record_date_only.startswith(normalized_date):
                continue
            
            _write_log(f"マッチ候補: SKU={sku}, 日付={record_date}, 店舗コード={record_store_code}")
            
            # レシート時刻より前のSKUのみを対象
            if receipt_datetime:
                try:
                    # 仕入データの時刻を取得
                    record_datetime_str = str(record.get('仕入れ日') or record.get('purchase_date') or '')
                    record_datetime = None
                    
                    if ' ' in record_datetime_str:
                        # 時刻が含まれている場合
                        # フォーマットを正規化（/を-に変換）
                        normalized_datetime_str = record_datetime_str.replace('/', '-')
                        # 複数のフォーマットに対応
                        datetime_formats = [
                            "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d %H:%M",
                            "%Y/%m/%d %H:%M:%S",
                            "%Y/%m/%d %H:%M",
                        ]
                        for fmt in datetime_formats:
                            try:
                                record_datetime = datetime.strptime(normalized_datetime_str, fmt)
                                break
                            except ValueError:
                                continue
                    else:
                        # 時刻が含まれていない場合は00:00:00として扱う
                        record_datetime = datetime.strptime(f"{record_date_only} 00:00:00", "%Y-%m-%d %H:%M:%S")
                    
                    if record_datetime is None:
                        # パースに失敗した場合は00:00:00として扱う
                        record_datetime = datetime.strptime(f"{record_date_only} 00:00:00", "%Y-%m-%d %H:%M:%S")
                    
                    # レシート時刻より後の場合はスキップ
                    if record_datetime >= receipt_datetime:
                        _write_log(f"時刻フィルタ: SKU={sku} はレシート時刻より後（{record_datetime} >= {receipt_datetime}）")
                        continue
                except Exception as e:
                    # 時刻の比較に失敗した場合はスキップ
                    _write_log(f"時刻比較エラー: SKU={sku}, エラー={e}, record_datetime_str={record_datetime_str}")
                    continue
            
            # 既にレシートIDが設定されているか確認
            # 仕入管理タブのデータに既にレシートIDがある場合はスキップ
            if inventory_records:
                existing_receipt_id = record.get('レシートID') or record.get('receipt_id') or ''
                if existing_receipt_id:
                    _write_log(f"スキップ: SKU={sku} は既にレシートID={existing_receipt_id}が設定されています")
                    continue
            
            # ProductDatabaseから現在のレシートIDを確認
            product = product_db.get_by_sku(sku)
            product_already_has_receipt_id = False
            if product:
                # productsテーブルに存在する場合
                if product.get('receipt_id'):
                    # 既にレシートIDが設定されている場合でも、UI更新は実行する
                    product_already_has_receipt_id = True
                    matched_count += 1
                    matched_skus.append(sku)
                    _write_log(f"情報: SKU={sku} はproductsテーブルに既にレシートID={product.get('receipt_id')}が設定されています（UI更新のみ実行）")
                else:
                    # レシートIDを設定
                    try:
                        # ProductDatabaseのlink_receiptメソッドを使用
                        # receipt_idは整数（DBのID）を使用
                        if product_db.link_receipt(sku, db_receipt_id):
                            updated_count += 1
                            matched_count += 1
                            matched_skus.append(sku)
                            _write_log(f"更新成功: SKU={sku} にレシートID={db_receipt_id}を設定")
                    except Exception as e:
                        # エラーはログに記録して続行
                        _write_log(f"エラー: SKU={sku}, エラー={e}")
            else:
                # productsテーブルに存在しない場合は、仕入DBのデータからproductsテーブルに登録
                try:
                    # 仕入DBのデータから商品情報を構築
                    product_data = {
                        "sku": sku,
                        "jan": record.get('JAN') or record.get('jan') or None,
                        "asin": record.get('ASIN') or record.get('asin') or None,
                        "product_name": record.get('商品名') or record.get('product_name') or None,
                        "purchase_date": record_date_only,
                        "purchase_price": record.get('仕入れ価格') or record.get('purchase_price') or None,
                        "quantity": record.get('仕入れ個数') or record.get('quantity') or None,
                        "store_code": store_code,
                        "store_name": record.get('店舗名') or record.get('store_name') or None,
                        "receipt_id": db_receipt_id,
                    }
                    # 数値型の変換
                    if product_data.get("purchase_price"):
                        try:
                            product_data["purchase_price"] = int(product_data["purchase_price"])
                        except (ValueError, TypeError):
                            product_data["purchase_price"] = None
                    if product_data.get("quantity"):
                        try:
                            product_data["quantity"] = int(product_data["quantity"])
                        except (ValueError, TypeError):
                            product_data["quantity"] = None
                    
                    # productsテーブルに登録
                    product_db.upsert(product_data)
                    updated_count += 1
                    matched_count += 1
                    matched_skus.append(sku)
                    _write_log(f"新規登録成功: SKU={sku} をproductsテーブルに登録（レシートID={db_receipt_id}）")
                except Exception as e:
                    # エラーはログに記録して続行
                    _write_log(f"新規登録エラー: SKU={sku}, エラー={e}")
            
            # 仕入管理タブのデータにもレシートIDを設定
            # inventory_dataが存在する場合はinventory_dataを更新
            # inventory_dataがNoneでも、filtered_dataが存在する場合はfiltered_dataを更新
            _write_log(f"デバッグ: inventory_data_exists={inventory_data_exists}, inventory_widget={self.inventory_widget is not None}, hasattr={hasattr(self.inventory_widget, 'inventory_data') if self.inventory_widget else False}, inventory_data={self.inventory_widget.inventory_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') else None}, filtered_data={self.inventory_widget.filtered_data is not None if self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') else None}")
            
            # inventory_dataが存在する場合
            if inventory_data_exists and self.inventory_widget and hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
                try:
                    import pandas as pd
                    _write_log(f"仕入管理タブ更新開始: SKU={sku}, inventory_data存在={self.inventory_widget.inventory_data is not None}")
                    
                    # レシートID列が存在しない場合は追加
                    if 'レシートID' not in self.inventory_widget.inventory_data.columns:
                        self.inventory_widget.inventory_data['レシートID'] = ''
                        _write_log("レシートID列を追加しました")
                    
                    # inventory_dataから該当SKUの行を検索
                    matched_in_inventory = False
                    target_sku_normalized = str(sku).strip().lower()
                    _write_log(f"SKU検索開始: target_sku='{sku}', normalized='{target_sku_normalized}'")
                    _write_log(f"inventory_data行数: {len(self.inventory_widget.inventory_data)}")
                    
                    for idx, row in self.inventory_widget.inventory_data.iterrows():
                        row_sku = str(row.get('SKU') or '').strip()
                        row_sku_normalized = row_sku.lower()
                        is_match = (row_sku == sku or 
                                   row_sku == str(sku).strip() or 
                                   row_sku_normalized == target_sku_normalized)
                        
                        if idx < 5:  # 最初の5行だけログ出力（デバッグ用）
                            _write_log(f"SKU比較[{idx}]: row_sku='{row_sku}', target_sku='{sku}', 一致={is_match}")
                        
                        if is_match:
                            # レシートIDを設定（カスタムIDを使用）
                            self.inventory_widget.inventory_data.at[idx, 'レシートID'] = receipt_id_str
                            matched_in_inventory = True
                            _write_log(f"仕入管理タブ更新成功: SKU={sku} (idx={idx}) にレシートID={receipt_id_str}を設定")
                            # 確認のため、設定後の値をログ出力
                            updated_value = self.inventory_widget.inventory_data.at[idx, 'レシートID']
                            _write_log(f"設定確認: idx={idx}のレシートID={updated_value}")
                            break
                    
                    if not matched_in_inventory:
                        _write_log(f"警告: SKU={sku} がinventory_dataに見つかりませんでした（全{len(self.inventory_widget.inventory_data)}行を検索）")
                    
                    # filtered_dataも更新（表示用）
                    if hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                        if 'レシートID' not in self.inventory_widget.filtered_data.columns:
                            self.inventory_widget.filtered_data['レシートID'] = ''
                        # filtered_dataからも該当SKUの行を検索して更新
                        matched_in_filtered = False
                        _write_log(f"filtered_data検索開始: target_sku='{sku}', filtered_data行数={len(self.inventory_widget.filtered_data)}")
                        for idx, row in self.inventory_widget.filtered_data.iterrows():
                            row_sku = str(row.get('SKU') or '').strip()
                            row_sku_normalized = row_sku.lower()
                            is_match = (row_sku == sku or 
                                       row_sku == str(sku).strip() or 
                                       row_sku_normalized == target_sku_normalized)
                            if is_match:
                                self.inventory_widget.filtered_data.at[idx, 'レシートID'] = receipt_id_str
                                matched_in_filtered = True
                                _write_log(f"filtered_data更新成功: SKU={sku} (idx={idx}) にレシートID={receipt_id_str}を設定")
                                # 確認のため、設定後の値をログ出力
                                updated_value = self.inventory_widget.filtered_data.at[idx, 'レシートID']
                                _write_log(f"filtered_data設定確認: idx={idx}のレシートID={updated_value}")
                                break
                        
                        if not matched_in_filtered:
                            _write_log(f"警告: SKU={sku} がfiltered_dataに見つかりませんでした（全{len(self.inventory_widget.filtered_data)}行を検索）")
                except Exception as e:
                    import traceback
                    _write_log(f"仕入管理タブ更新エラー: SKU={sku}, エラー={e}\n{traceback.format_exc()}")
            
            # inventory_dataがNoneでも、filtered_dataが存在する場合はfiltered_dataを更新
            elif self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                try:
                    import pandas as pd
                    _write_log(f"filtered_dataのみ更新開始: SKU={sku}, filtered_data存在={self.inventory_widget.filtered_data is not None}")
                    
                    # レシートID列が存在しない場合は追加
                    if 'レシートID' not in self.inventory_widget.filtered_data.columns:
                        self.inventory_widget.filtered_data['レシートID'] = ''
                        _write_log("filtered_dataにレシートID列を追加しました")
                    
                    # filtered_dataから該当SKUの行を検索して更新
                    matched_in_filtered = False
                    target_sku_normalized = str(sku).strip().lower()
                    _write_log(f"filtered_data検索開始: target_sku='{sku}', normalized='{target_sku_normalized}'")
                    _write_log(f"filtered_data行数: {len(self.inventory_widget.filtered_data)}")
                    
                    for idx, row in self.inventory_widget.filtered_data.iterrows():
                        row_sku = str(row.get('SKU') or '').strip()
                        row_sku_normalized = row_sku.lower()
                        is_match = (row_sku == sku or 
                                   row_sku == str(sku).strip() or 
                                   row_sku_normalized == target_sku_normalized)
                        
                        if is_match:
                            self.inventory_widget.filtered_data.at[idx, 'レシートID'] = receipt_id_str
                            matched_in_filtered = True
                            _write_log(f"filtered_data更新成功: SKU={sku} (idx={idx}) にレシートID={receipt_id_str}を設定")
                            # 確認のため、設定後の値をログ出力
                            updated_value = self.inventory_widget.filtered_data.at[idx, 'レシートID']
                            _write_log(f"filtered_data設定確認: idx={idx}のレシートID={updated_value}")
                            break
                    
                    if not matched_in_filtered:
                        _write_log(f"警告: SKU={sku} がfiltered_dataに見つかりませんでした（全{len(self.inventory_widget.filtered_data)}行を検索）")
                except Exception as e:
                    import traceback
                    _write_log(f"filtered_data更新エラー: SKU={sku}, エラー={e}\n{traceback.format_exc()}")
        
        # 結果をログに記録
        _write_log(f"完了: マッチ={matched_count}件, 更新={updated_count}件, レシートID={receipt_id_str}, 対象SKU={matched_skus}")
        
        # 仕入管理タブのテーブル表示を更新（ループの外で一度だけ）
        # inventory_dataが存在する場合、またはfiltered_dataが存在する場合は更新する
        has_filtered_data = self.inventory_widget and hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None
        _write_log(f"テーブル更新チェック: matched_count={matched_count}, inventory_data_exists={inventory_data_exists}, has_filtered_data={has_filtered_data}, inventory_widget={self.inventory_widget is not None}, has_update_table={hasattr(self.inventory_widget, 'update_table') if self.inventory_widget else False}")
        if matched_count > 0 and self.inventory_widget and hasattr(self.inventory_widget, 'update_table') and (inventory_data_exists or has_filtered_data):
            try:
                _write_log("仕入管理タブのテーブル表示を更新します")
                # 更新前のレシートID値を確認
                sample_skus = matched_skus[:3] if len(matched_skus) > 0 else []
                for sample_sku in sample_skus:
                    if hasattr(self.inventory_widget, 'inventory_data') and self.inventory_widget.inventory_data is not None:
                        for idx, row in self.inventory_widget.inventory_data.iterrows():
                            if str(row.get('SKU') or '').strip() == sample_sku:
                                receipt_id_value = row.get('レシートID', '')
                                _write_log(f"更新前確認(inventory_data): SKU={sample_sku}, レシートID={receipt_id_value}")
                                break
                    elif hasattr(self.inventory_widget, 'filtered_data') and self.inventory_widget.filtered_data is not None:
                        for idx, row in self.inventory_widget.filtered_data.iterrows():
                            if str(row.get('SKU') or '').strip() == sample_sku:
                                receipt_id_value = row.get('レシートID', '')
                                _write_log(f"更新前確認(filtered_data): SKU={sample_sku}, レシートID={receipt_id_value}")
                                break
                self.inventory_widget.update_table()
                _write_log("仕入管理タブのテーブル表示を更新しました")
            except Exception as e:
                import traceback
                _write_log(f"テーブル更新エラー: {e}\n{traceback.format_exc()}")
        else:
            _write_log("テーブル更新をスキップしました（条件を満たしていません）")
            # inventory_dataもfiltered_dataもNoneの場合、テーブルから直接レシートIDを設定
            if matched_count > 0 and self.inventory_widget and hasattr(self.inventory_widget, 'data_table'):
                try:
                    from PySide6.QtWidgets import QTableWidgetItem
                    _write_log("テーブルから直接レシートIDを設定します")
                    data_table = self.inventory_widget.data_table
                    row_count = data_table.rowCount()
                    _write_log(f"テーブル行数: {row_count}")
                    
                    # カラムヘッダーからSKUとレシートIDのインデックスを取得
                    column_headers = []
                    if hasattr(self.inventory_widget, 'column_headers'):
                        column_headers = self.inventory_widget.column_headers
                    else:
                        # カラムヘッダーが取得できない場合は、デフォルトの順序を使用
                        column_headers = [
                            "仕入れ日", "コンディション", "SKU", "ASIN", "JAN", "商品名", "仕入れ個数",
                            "仕入れ価格", "販売予定価格", "見込み利益", "損益分岐点", "コメント",
                            "発送方法", "仕入先", "コンディション説明", "保証期間", "レシートID"
                        ]
                    
                    sku_column_idx = column_headers.index("SKU") if "SKU" in column_headers else 2
                    receipt_id_column_idx = column_headers.index("レシートID") if "レシートID" in column_headers else 16
                    _write_log(f"SKU列インデックス: {sku_column_idx}, レシートID列インデックス: {receipt_id_column_idx}")
                    
                    # テーブルの各行を検索して、該当するSKUの行にレシートIDを設定
                    updated_rows = 0
                    for row_idx in range(row_count):
                        sku_item = data_table.item(row_idx, sku_column_idx)
                        if sku_item:
                            row_sku = str(sku_item.text()).strip()
                            # SKUが「未実装」の場合はスキップ
                            if row_sku == "未実装" or not row_sku:
                                continue
                            
                            # マッチしたSKUか確認
                            if row_sku in matched_skus:
                                # レシートIDを設定
                                receipt_id_item = data_table.item(row_idx, receipt_id_column_idx)
                                if receipt_id_item:
                                    receipt_id_item.setText(receipt_id_str)
                                else:
                                    receipt_id_item = QTableWidgetItem(receipt_id_str)
                                    data_table.setItem(row_idx, receipt_id_column_idx, receipt_id_item)
                                updated_rows += 1
                                _write_log(f"テーブル直接更新: 行={row_idx}, SKU={row_sku}, レシートID={receipt_id_str}")
                    
                    _write_log(f"テーブル直接更新完了: {updated_rows}行を更新しました")
                except Exception as e:
                    import traceback
                    _write_log(f"テーブル直接更新エラー: {e}\n{traceback.format_exc()}")
        
        if matched_count > 0 or updated_count > 0:
            # 商品DBタブの表示を更新（メソッドが存在する場合）
            if self.product_widget and hasattr(self.product_widget, 'load_products'):
                try:
                    self.product_widget.load_products()
                except Exception:
                    pass
            
            # 仕入DBタブ（ProductWidget内）のレシートIDを更新
            if self.product_widget and hasattr(self.product_widget, 'purchase_all_records'):
                try:
                    _write_log("仕入DBタブ（ProductWidget）のレシートIDを更新します")
                    updated_purchase_records = 0
                    for record in self.product_widget.purchase_all_records:
                        sku = record.get('SKU') or record.get('sku') or ''
                        if sku in matched_skus:
                            record['レシートID'] = receipt_id_str
                            updated_purchase_records += 1
                            _write_log(f"仕入DBタブ更新: SKU={sku}, レシートID={receipt_id_str}")
                    
                    # テーブルを再描画
                    if hasattr(self.product_widget, 'populate_purchase_table'):
                        self.product_widget.populate_purchase_table(self.product_widget.purchase_all_records)
                        _write_log(f"仕入DBタブテーブル再描画完了: {updated_purchase_records}件のレシートIDを更新しました")
                except Exception as e:
                    import traceback
                    _write_log(f"仕入DBタブ更新エラー: {e}\n{traceback.format_exc()}")
    
    def reset_form(self):
        """フォームをリセット"""
        self.current_receipt_id = None
        self.current_receipt_data = None
        self.date_edit.setDate(QDate.currentDate())
        self.time_edit.clear()
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
            
            # 時刻を表示
            purchase_time = receipt.get('purchase_time')
            self.time_edit.setText(purchase_time or "")
            
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

