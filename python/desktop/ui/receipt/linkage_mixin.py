#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画像プレビュー・SKU手動紐付け mixin。"""
from __future__ import annotations

import os
import re
import sys
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QMessageBox, QFileDialog, QDialog,
    QDialogButtonBox, QTextEdit, QDateEdit, QSpinBox,
    QScrollArea, QSizePolicy, QStyledItemDelegate,
    QSplitter, QListWidget, QListWidgetItem, QMenu,
    QFormLayout, QApplication, QCheckBox, QProgressDialog,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QSettings, QTimer, QUrl, QCoreApplication
from PySide6.QtGui import QPixmap, QTransform, QColor, QDesktopServices, QClipboard

_desktop_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _desktop_root in sys.path:
    sys.path.remove(_desktop_root)
sys.path.insert(0, _desktop_root)

from desktop.utils.ui_utils import save_table_header_state, restore_table_header_state
from desktop.utils.route_utils import mark_route_evidence_completed

try:
    from services.receipt_service import ReceiptService
    from services.receipt_matching_service import ReceiptMatchingService
    from services.purchase_break_even import compute_break_even_for_record
    from services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
except Exception:
    from desktop.services.receipt_service import ReceiptService
    from desktop.services.receipt_matching_service import ReceiptMatchingService
    from desktop.services.purchase_break_even import compute_break_even_for_record
    from desktop.services.receipt_purchase_price_policy import (
        RECEIPT_MUTATES_PURCHASE_DB_PRICE,
        RECEIPT_PRICE_DIFFERENCE_TOLERANCE,
        is_acceptable_price_difference,
    )
    from desktop.services.receipt_sku_linking import (
        build_manual_candidate_entries,
        collect_link_skus_for_receipt,
        sort_receipts_for_bulk_matching,
    )
from database.receipt_db import ReceiptDatabase
from database.inventory_db import InventoryDatabase
from database.store_db import StoreDatabase
from database.account_title_db import AccountTitleDatabase
from database.product_db import ProductDatabase
from database.route_db import RouteDatabase

from .support import (
    ReceiptOCRThread,
    ReceiptSnapshotDialog,
    _RECEIPT_ACTION_TO_PIPELINE_STEP,
    _RECEIPT_WORKFLOW_PIPELINE_SEGMENTS,
    _format_receipt_status_prefix_html,
    _format_receipt_workflow_pipeline_html,
    AccountTitleDelegate,
    StoreNameDelegate,
    WarrantyProductDelegate,
)


class ReceiptLinkageMixin:
    def _show_image_popup(self, image_path: str, receipt_id: Optional[int] = None):
        """指定パスの画像をポップアップ表示（回転機能付き・編集パネル付き）"""
        from pathlib import Path
        image_file = Path(image_path)
        if not image_file.exists():
            QMessageBox.warning(self, "警告", f"画像ファイルが存在しません:\n{image_path}")
            return

        # レシートIDが指定されていない場合は画像パスから検索
        if receipt_id is None:
            receipts = self.receipt_db.find_by_date_and_store(None)
            for receipt in receipts:
                if receipt.get('file_path') == str(image_path) or receipt.get('original_file_path') == str(image_path):
                    receipt_id = receipt.get('id')
                    break
        
        # レシートデータを取得
        receipt_data = None
        if receipt_id:
            receipt_data = self.receipt_db.get_receipt(receipt_id)

        # 元の画像を読み込み（回転状態を保持するため）
        original_pixmap = QPixmap(str(image_file))
        if original_pixmap.isNull():
            QMessageBox.warning(self, "警告", "画像を読み込めませんでした。")
            return
        
        # 現在の回転角度を保持（0度から開始）
        current_rotation = [0]  # リストで保持して参照渡しにする
        
        dialog = QDialog(self)
        dialog.setWindowTitle(str(image_file.name))
        dialog.setMinimumSize(1200, 800)
        # 最大化・最小化ボタンを有効にして編集しやすくする
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)

        screen = dialog.screen().availableGeometry()
        max_dialog_width = int(screen.width() * 0.95)
        max_dialog_height = int(screen.height() * 0.95)

        def update_image_display():
            """画像を回転させて表示を更新"""
            # 回転を適用
            transform = QTransform().rotate(current_rotation[0])
            rotated_pixmap = original_pixmap.transformed(transform, Qt.SmoothTransformation)
            
            # サイズ調整
            rotated_width = rotated_pixmap.width()
            rotated_height = rotated_pixmap.height()
            
            if rotated_width > max_dialog_width or rotated_height > max_dialog_height:
                scaled_pixmap = rotated_pixmap.scaled(
                    max_dialog_width, max_dialog_height,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            else:
                scaled_pixmap = rotated_pixmap
            
            # ラベルに設定
            image_label.setPixmap(scaled_pixmap)
            
            # ダイアログサイズを調整
            dialog_width = min(scaled_pixmap.width() + 40, max_dialog_width)
            dialog_height = min(scaled_pixmap.height() + 100, max_dialog_height)
            dialog.resize(dialog_width, dialog_height)
            
            # 情報ラベルを更新
            info_label.setText(f"画像サイズ: {rotated_width} x {rotated_height} px (回転: {current_rotation[0]}°)")

        def rotate_image(angle: int):
            """画像を回転"""
            current_rotation[0] = (current_rotation[0] + angle) % 360
            update_image_display()

        def save_rotation():
            """回転を実ファイルに保存"""
            if current_rotation[0] == 0:
                QMessageBox.information(self, "情報", "回転が適用されていません。")
                return
            
            # 回転を適用した画像を作成
            transform = QTransform().rotate(current_rotation[0])
            rotated_pixmap = original_pixmap.transformed(transform, Qt.SmoothTransformation)
            
            # ファイルに保存
            if not rotated_pixmap.save(str(image_file)):
                QMessageBox.warning(self, "警告", "画像の保存に失敗しました。")
                return
            
            # 元の画像を更新（次回表示時に回転済み画像が表示される）
            original_pixmap.load(str(image_file))
            current_rotation[0] = 0  # リセット
            update_image_display()
            
            # レシート一覧を更新（サムネイルが更新される可能性があるため）
            self.refresh_receipt_list()
            
            QMessageBox.information(self, "完了", "画像の回転を保存しました。")

        # 初期表示用のサイズ計算
        original_width = original_pixmap.width()
        original_height = original_pixmap.height()
        
        if original_width > max_dialog_width or original_height > max_dialog_height:
            scaled_pixmap = original_pixmap.scaled(
                max_dialog_width, max_dialog_height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            scaled_pixmap = original_pixmap

        dialog_width = min(scaled_pixmap.width() + 40, max_dialog_width)
        dialog_height = min(scaled_pixmap.height() + 100, max_dialog_height)

        # メインレイアウト（横分割）
        main_layout = QHBoxLayout(dialog)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 左側：画像表示エリア
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # 回転ボタン
        rotate_layout = QHBoxLayout()
        rotate_left_btn = QPushButton("⟲ 左回転")
        rotate_left_btn.clicked.connect(lambda: rotate_image(-90))
        rotate_layout.addWidget(rotate_left_btn)
        
        rotate_right_btn = QPushButton("右回転 ⟳")
        rotate_right_btn.clicked.connect(lambda: rotate_image(90))
        rotate_layout.addWidget(rotate_right_btn)
        
        save_rotation_btn = QPushButton("回転を保存")
        save_rotation_btn.clicked.connect(save_rotation)
        save_rotation_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        rotate_layout.addWidget(save_rotation_btn)
        rotate_layout.addStretch()
        left_layout.addLayout(rotate_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setAlignment(Qt.AlignCenter)

        image_label = QLabel()
        image_label.setPixmap(scaled_pixmap)
        image_label.setAlignment(Qt.AlignCenter)
        scroll_area.setWidget(image_label)
        left_layout.addWidget(scroll_area)

        info_label = QLabel(f"画像サイズ: {original_width} x {original_height} px")
        info_label.setStyleSheet("color: #888888; font-size: 10px;")
        left_layout.addWidget(info_label)

        main_layout.addWidget(left_widget, 2)  # 画像エリアは2倍の幅

        # 右側：編集パネル
        if receipt_data:
            right_widget = QWidget()
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(10)

            # 編集フォーム
            form_group = QGroupBox("レシート情報編集")
            form_layout = QFormLayout(form_group)
            
            # 種別
            type_combo = QComboBox()
            type_combo.addItems(["レシート", "保証書", "その他"])
            if receipt_data.get('account_title'):
                # account_titleから種別を推測（簡易版）
                account_title = receipt_data.get('account_title', '')
                if '保証書' in account_title:
                    type_combo.setCurrentText("保証書")
                elif 'レシート' in account_title:
                    type_combo.setCurrentText("レシート")
            form_layout.addRow("種別:", type_combo)
            
            # 科目
            account_title_combo = QComboBox()
            account_title_combo.setEditable(True)
            # 勘定科目を読み込み
            try:
                account_title_db = AccountTitleDatabase()
                titles = account_title_db.get_all_titles()
                account_titles = [title.get('name', '') for title in titles if title.get('name')]
                
                # デフォルト科目「仕入」を追加（まだない場合）
                default_title = "仕入"
                if default_title not in account_titles:
                    account_titles.insert(0, default_title)
                
                # プルダウンに科目を追加
                for title in account_titles:
                    account_title_combo.addItem(title)
                
                # 現在の科目を設定
                current_title = receipt_data.get('account_title', '') or default_title
                idx = account_title_combo.findText(current_title)
                if idx >= 0:
                    account_title_combo.setCurrentIndex(idx)
                else:
                    account_title_combo.setCurrentText(current_title)
            except Exception as e:
                # エラー時はデフォルト科目のみ追加
                account_title_combo.addItem("仕入")
                account_title_combo.setCurrentText("仕入")
            form_layout.addRow("科目:", account_title_combo)
            
            # レシートID
            
            # 日付
            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            purchase_date = receipt_data.get('purchase_date')
            if purchase_date:
                try:
                    date = QDate.fromString(purchase_date, "yyyy/MM/dd")
                    if not date.isValid():
                        date = QDate.fromString(purchase_date.replace("/", "-"), "yyyy-MM-dd")
                    if date.isValid():
                        date_edit.setDate(date)
                except Exception:
                    date_edit.setDate(QDate.currentDate())
            else:
                date_edit.setDate(QDate.currentDate())
            form_layout.addRow("日付:", date_edit)
            
            # 時刻
            time_edit = QLineEdit()
            time_edit.setText(receipt_data.get('purchase_time') or '')
            time_edit.setPlaceholderText("HH:MM")
            form_layout.addRow("時刻:", time_edit)
            
            # 店舗名（プルダウンで店舗コード＋店舗名を選択可能）
            store_name_combo = QComboBox()
            store_name_combo.setEditable(False)
            
            def load_store_combo():
                """店舗名プルダウンを読み込む（日付に基づいて優先店舗を表示）"""
                # 現在選択されている店舗コードを保持
                current_selected_code = store_name_combo.currentData() if store_name_combo.count() > 0 else None
                if not current_selected_code:
                    current_selected_code = receipt_data.get('store_code', '') or ''
                
                # プルダウンをクリア
                store_name_combo.clear()
                
                # 現在の日付を取得
                purchase_date_val = date_edit.date()
                purchase_date_str = purchase_date_val.toString("yyyy-MM-dd") if purchase_date_val.isValid() else ""
                
                print(f"[レシート情報編集] 店舗名プルダウン読み込み: 日付={purchase_date_str}")
                
                # 仕入DBから同じ日付の店舗コードを取得（優先表示用）
                priority_store_codes = set()
                if self.product_widget and purchase_date_str:
                    try:
                        from datetime import datetime
                        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                        if not purchase_records:
                            print(f"[レシート情報編集] 仕入DBにレコードがありません")
                        else:
                            print(f"[レシート情報編集] 仕入DBレコード数: {len(purchase_records)}")
                        
                        receipt_date_obj = None
                        try:
                            receipt_date_obj = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
                            print(f"[レシート情報編集] 比較対象日付: {receipt_date_obj}")
                        except Exception as e:
                            print(f"[レシート情報編集] 日付パースエラー: {e}")
                        
                        if receipt_date_obj:
                            matched_count = 0
                            for record in purchase_records:
                                record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                                if not record_date:
                                    continue
                                
                                try:
                                    record_date_str = str(record_date).strip()
                                    original_record_date_str = record_date_str
                                    if " " in record_date_str:
                                        record_date_str = record_date_str.split(" ")[0]
                                    if "T" in record_date_str:
                                        record_date_str = record_date_str.split("T")[0]
                                    
                                    record_date_obj = None
                                    # 様々な日付フォーマットに対応
                                    date_formats = [
                                        ("%Y-%m-%d", record_date_str[:10]),
                                        ("%Y/%m/%d", record_date_str[:10]),
                                        ("%Y-%m-%d", record_date_str[:10].replace("/", "-")),
                                        ("%Y/%m/%d", record_date_str[:10].replace("-", "/")),
                                    ]
                                    
                                    for fmt, date_str in date_formats:
                                        try:
                                            record_date_obj = datetime.strptime(date_str, fmt).date()
                                            break
                                        except:
                                            continue
                                    
                                    # それでもパースできない場合は、文字列の先頭10文字を直接比較
                                    if not record_date_obj:
                                        try:
                                            # YYYY-MM-DD または YYYY/MM/DD 形式を想定
                                            normalized_record = record_date_str[:10].replace("/", "-")
                                            normalized_receipt = purchase_date_str.replace("/", "-")
                                            if normalized_record == normalized_receipt:
                                                # 文字列が一致する場合は、強制的に日付オブジェクトを作成
                                                record_date_obj = datetime.strptime(normalized_record, "%Y-%m-%d").date()
                                        except:
                                            pass
                                    
                                    if record_date_obj and record_date_obj == receipt_date_obj:
                                        matched_count += 1
                                        # 仕入DBでは「仕入先」カラムに店舗コードが格納されている
                                        record_store_code = record.get('仕入先') or record.get('店舗コード') or record.get('store_code', '')
                                        if record_store_code:
                                            # 店舗コードのみを取得（表示ラベルから抽出）
                                            store_code_clean = str(record_store_code).strip()
                                            if " " in store_code_clean:
                                                store_code_clean = store_code_clean.split(" ")[0]
                                            if store_code_clean:
                                                priority_store_codes.add(store_code_clean)
                                                print(f"[レシート情報編集] 優先店舗コード追加: {store_code_clean} (元の値: {record_store_code}, 日付: {original_record_date_str})")
                                except Exception:
                                    continue
                            print(f"[レシート情報編集] 日付一致レコード数: {matched_count}, 優先店舗コード数: {len(priority_store_codes)}")
                    except Exception as e:
                        import traceback
                        print(f"[レシート情報編集] 店舗コード取得エラー: {e}\n{traceback.format_exc()}")
                
                # 店舗マスタから全店舗を読み込み
                try:
                    stores = self.store_db.list_stores()
                    print(f"[レシート情報編集] 店舗マスタ数: {len(stores)}")
                    priority_stores = []
                    other_stores = []
                    
                    for store in stores:
                        # 店舗コードを優先し、空の場合は仕入れ先コードをフォールバックとして使用
                        code = (store.get('store_code') or '').strip() or (store.get('supplier_code') or '').strip()
                        name = (store.get('store_name') or '').strip()
                        
                        if code and name:
                            label = f"{code} {name}"
                        elif code:
                            label = code
                        elif name:
                            label = name
                        else:
                            continue
                        
                        # 優先店舗コードに含まれている場合は優先リストに、そうでなければ通常リストに
                        if code in priority_store_codes:
                            priority_stores.append((label, code))
                            print(f"[レシート情報編集] 優先店舗追加: {label} (コード: {code})")
                        else:
                            other_stores.append((label, code))
                    
                    print(f"[レシート情報編集] 優先店舗数: {len(priority_stores)}, 通常店舗数: {len(other_stores)}")
                    
                    # 優先店舗を先に追加
                    for label, code in priority_stores:
                        store_name_combo.addItem(label, code)
                    
                    # 優先店舗と通常店舗の間に区切りを追加（優先店舗がある場合のみ）
                    if priority_stores and other_stores:
                        store_name_combo.insertSeparator(store_name_combo.count())
                    
                    # 通常店舗を追加
                    for label, code in other_stores:
                        store_name_combo.addItem(label, code)
                    
                    # 経費先一覧からも店舗名候補を追加（店舗マスタにない経費先も選択可能に）
                    added_codes = {code for _, code in priority_stores + other_stores}
                    try:
                        dests = self.store_db.list_expense_destinations()
                        expense_items = []
                        for d in dests:
                            code = (d.get('code') or '').strip()
                            name = (d.get('name') or '').strip()
                            if code and code not in added_codes:
                                label = f"{code} {name}" if name else code
                                expense_items.append((label, code))
                                added_codes.add(code)
                        if expense_items:
                            store_name_combo.insertSeparator(store_name_combo.count())
                            for label, code in expense_items:
                                store_name_combo.addItem(label, code)
                            print(f"[レシート情報編集] 経費先追加数: {len(expense_items)}")
                    except Exception as ex:
                        import traceback
                        print(f"[レシート情報編集] 経費先読み込みエラー: {ex}\n{traceback.format_exc()}")
                    
                    print(f"[レシート情報編集] プルダウン項目数: {store_name_combo.count()}")
                    
                    # 以前選択されていた店舗コードに一致する項目を選択
                    if current_selected_code:
                        idx = store_name_combo.findData(current_selected_code)
                        if idx >= 0:
                            store_name_combo.setCurrentIndex(idx)
                            print(f"[レシート情報編集] 以前の選択を復元: {current_selected_code} (インデックス: {idx})")
                        else:
                            print(f"[レシート情報編集] 以前の選択が見つかりません: {current_selected_code}")
                except Exception as e:
                    import traceback
                    print(f"[レシート情報編集] 店舗マスタ読み込みエラー: {e}\n{traceback.format_exc()}")
            
            # 初期読み込み
            load_store_combo()
            
            # 日付変更時に店舗名プルダウンを再読み込み
            date_edit.dateChanged.connect(load_store_combo)
            
            form_layout.addRow("店舗名:", store_name_combo)
            
            # 登録番号（T + 13桁、手動編集可能）
            registration_edit = QLineEdit()
            registration_edit.setText(receipt_data.get('registration_number') or '')
            registration_edit.setPlaceholderText("例: T1234567890123")
            form_layout.addRow("登録番号:", registration_edit)
            
            # 電話番号
            phone_edit = QLineEdit()
            phone_edit.setText(receipt_data.get('phone_number') or '')
            form_layout.addRow("電話番号:", phone_edit)
            
            # 合計
            total_edit = QLineEdit()
            total_edit.setText(str(receipt_data.get('total_amount') or ''))
            form_layout.addRow("合計:", total_edit)
            
            # 値引
            discount_edit = QLineEdit()
            discount_edit.setText(str(receipt_data.get('discount_amount') or ''))
            form_layout.addRow("値引:", discount_edit)
            
            # 点数
            # 店舗コード（店舗名コンボボックスと連動）
            # 店舗名コンボボックスで選択した店舗コードを表示（読み取り専用）
            store_code_display = QLineEdit()
            store_code_display.setReadOnly(True)
            current_store_code = receipt_data.get('store_code', '') or ''
            store_code_display.setText(current_store_code)
            form_layout.addRow("店舗コード:", store_code_display)
            
            # 店舗名コンボボックスの変更時に店舗コード表示を更新
            def update_store_code_display():
                selected_code = store_name_combo.currentData()
                store_code_display.setText(selected_code if selected_code else '')
            store_name_combo.currentIndexChanged.connect(update_store_code_display)
            
            right_layout.addWidget(form_group)
            
            # SKU紐付けセクション（科目が「仕入」の場合のみ表示）
            sku_group = QGroupBox("紐付けSKU")
            sku_layout = QVBoxLayout(sku_group)
            
            # 科目が「仕入」かどうかを判定する関数
            def is_purchase_account(title):
                """科目が「仕入」かどうかを判定"""
                return title and title.strip() == "仕入"
            
            # 初期表示状態を設定（科目が「仕入」の場合のみ表示）
            current_account_title = account_title_combo.currentText()
            sku_group.setVisible(is_purchase_account(current_account_title))
            
            # 科目変更時に紐付けSKUセクションの表示/非表示を切り替え
            def on_account_title_changed(title):
                """科目が変更された時の処理"""
                is_purchase = is_purchase_account(title)
                sku_group.setVisible(is_purchase)
                
                # 科目が「仕入」以外の場合、紐付けSKUをクリア
                if not is_purchase:
                    linked_skus_list.clear()
                    # 差額表示も更新
                    if hasattr(sku_group, 'total_label'):
                        total_label = sku_group.findChild(QLabel, "sku_total_label")
                        if total_label:
                            total_label.setText("合計: ¥0 (差額: ¥0)")
            
            account_title_combo.currentTextChanged.connect(on_account_title_changed)
            
            # 現在の紐付けSKUリスト
            linked_skus_list = QListWidget()
            linked_skus_list.setMaximumHeight(150)
            linked_skus_text = receipt_data.get('linked_skus', '') or ''
            
            # SKUと金額・時刻のマッピングを保持（仕入DBから取得：仕入れ個数 × 仕入れ価格）
            sku_info_map = {}  # {sku: {'price': total_amount, 'time': time_str}}
            if self.product_widget:
                purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                for record in purchase_records:
                    sku = record.get('SKU') or record.get('sku', '')
                    if sku and sku.strip():
                        sku = sku.strip()
                        # 仕入れ価格を取得（複数のカラム名に対応）
                        price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                        try:
                            price = float(price) if price else 0
                        except (ValueError, TypeError):
                            price = 0
                        # 仕入れ個数を取得（複数のカラム名に対応）
                        quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                        try:
                            quantity = float(quantity) if quantity else 1
                        except (ValueError, TypeError):
                            quantity = 1
                        # 金額 = 仕入れ個数 × 仕入れ価格
                        total_amount = price * quantity
                        
                        # 時刻情報を取得
                        time_str = "時刻不明"
                        
                        # 1. 「仕入れ日」カラムから取得（優先）- 「YYYY/MM/DD HH:MM」形式で日付と時刻の両方が含まれる
                        purchase_date_str = record.get('仕入れ日') or record.get('purchase_date') or ""
                        if purchase_date_str:
                            try:
                                from datetime import datetime
                                purchase_date_str_clean = str(purchase_date_str).strip()
                                # 「YYYY/MM/DD HH:MM」形式を想定
                                if ' ' in purchase_date_str_clean:
                                    try:
                                        # 「YYYY/MM/DD HH:MM」形式
                                        dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            # 「YYYY-MM-DD HH:MM」形式
                                            dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            try:
                                                # 「YYYY/MM/DD HH:MM:SS」形式
                                                dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                            except:
                                                try:
                                                    # 「YYYY-MM-DD HH:MM:SS」形式
                                                    dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M:%S")
                                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                                except:
                                                    # パースできない場合はそのまま使用
                                                    time_str = purchase_date_str_clean
                            except Exception as e:
                                print(f"時刻情報取得エラー (仕入れ日): {e}, 値: {purchase_date_str}")
                        
                        # 2. 「日付/時間」または「日付/時刻」カラムから取得
                        if time_str == "時刻不明":
                            datetime_str = record.get('日付/時間') or record.get('日付/時刻') or ""
                            if datetime_str:
                                try:
                                    from datetime import datetime
                                    datetime_str_clean = str(datetime_str).strip()
                                    if ' ' in datetime_str_clean:
                                        try:
                                            dt = datetime.strptime(datetime_str_clean, "%Y/%m/%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            try:
                                                dt = datetime.strptime(datetime_str_clean, "%Y-%m-%d %H:%M")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                            except:
                                                time_str = datetime_str_clean
                                    elif 'T' in datetime_str_clean:
                                        try:
                                            if datetime_str_clean.endswith('Z'):
                                                datetime_str_clean = datetime_str_clean[:-1]
                                            if len(datetime_str_clean) >= 19:
                                                dt = datetime.strptime(datetime_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            pass
                                except Exception:
                                    pass
                        
                        # 3. 「仕入れ時刻」または「purchase_time」カラムから取得
                        if time_str == "時刻不明":
                            record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                            if record_time:
                                try:
                                    from datetime import datetime
                                    record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                                    if record_date:
                                        date_str = str(record_date).strip()
                                        if " " in date_str:
                                            date_str = date_str.split(" ")[0]
                                        if "T" in date_str:
                                            date_str = date_str.split("T")[0]
                                        date_str = date_str.replace("/", "-")
                                        datetime_str = f"{date_str} {record_time}"
                                        try:
                                            dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            time_str = f"{date_str} {record_time}"
                                except Exception:
                                    pass
                        
                        # 4. created_atから時刻を取得（最後のフォールバック）
                        if time_str == "時刻不明":
                            record_created_at = record.get('created_at') or record.get('登録日時') or ""
                            if record_created_at:
                                try:
                                    from datetime import datetime
                                    if isinstance(record_created_at, str):
                                        record_created_at_clean = str(record_created_at).strip()
                                        if 'T' in record_created_at_clean:
                                            if record_created_at_clean.endswith('Z'):
                                                record_created_at_clean = record_created_at_clean[:-1]
                                            if len(record_created_at_clean) >= 19:
                                                dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        elif ' ' in record_created_at_clean:
                                            if len(record_created_at_clean) >= 19:
                                                dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except Exception:
                                    pass
                        
                        sku_info_map[sku] = {
                            'price': total_amount,
                            'time': time_str
                        }
            
            # 紐付けSKUリストに価格情報と時刻情報も表示
            total_price = 0
            if linked_skus_text:
                linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()]
                for sku in linked_skus:
                    sku_info = sku_info_map.get(sku, {})
                    price = sku_info.get('price', 0)
                    time_str = sku_info.get('time', '時刻不明')
                    
                    if price > 0:
                        display_text = f"{sku} - ¥{int(price):,} - ({time_str})"
                        total_price += price
                    else:
                        display_text = f"{sku} - 価格不明 - ({time_str})"
                    linked_skus_list.addItem(display_text)
                    # UserRoleにSKUを保存（削除時に使用）
                    item = linked_skus_list.item(linked_skus_list.count() - 1)
                    if item:
                        item.setData(Qt.UserRole, sku)
            
            sku_layout.addWidget(QLabel("現在の紐付けSKU:"))
            # ダブルクリックで価格編集可能にする
            linked_skus_list.itemDoubleClicked.connect(lambda item: self._edit_sku_price(item, linked_skus_list, total_edit, discount_edit))
            sku_layout.addWidget(linked_skus_list)
            
            # 合計金額と差額を表示（後で更新できるように変数に保存）
            receipt_total = int(receipt_data.get('total_amount') or 0)
            difference = total_price - receipt_total
            difference_text, difference_color = self._format_price_difference_display(difference)
            
            total_label = QLabel(f"合計: ¥{int(total_price):,} ({difference_text})")
            total_label.setStyleSheet(f"font-weight: bold; font-size: 12pt; color: {difference_color};")
            total_label.setObjectName("sku_total_label")  # 後で検索できるようにオブジェクト名を設定
            sku_layout.addWidget(total_label)
            
            # 合計が変更されたときに差額を更新（linked_skus_listが定義された後に接続）
            def update_total_on_change():
                try:
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                    self._update_sku_total(linked_skus_list, receipt_total)
                except ValueError:
                    self._update_sku_total(linked_skus_list, 0)
            total_edit.textChanged.connect(update_total_on_change)
            
            # SKU削除ボタン
            remove_sku_btn = QPushButton("選択SKUを削除")
            remove_sku_btn.clicked.connect(lambda: self._remove_sku_from_list(linked_skus_list, total_edit))
            sku_layout.addWidget(remove_sku_btn)
            
            # 仕入DBから候補SKUを取得
            candidate_skus_list = QListWidget()
            candidate_skus_list.setMaximumHeight(150)
            candidate_skus_list.setSelectionMode(QListWidget.MultiSelection)
            sku_layout.addWidget(QLabel("仕入DBの候補SKU:"))
            sku_layout.addWidget(candidate_skus_list)
            
            # 時刻情報を取得する関数（sku_info_mapと同じロジック）
            def get_time_from_record(record):
                """レコードから時刻情報を取得"""
                time_str = "時刻不明"
                
                # 1. 「仕入れ日」カラムから取得（優先）
                purchase_date_str = record.get('仕入れ日') or record.get('purchase_date') or ""
                if purchase_date_str:
                    try:
                        from datetime import datetime
                        purchase_date_str_clean = str(purchase_date_str).strip()
                        if ' ' in purchase_date_str_clean:
                            try:
                                dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M")
                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                            except:
                                try:
                                    dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M")
                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    try:
                                        dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M:%S")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            time_str = purchase_date_str_clean
                    except Exception:
                        pass
                
                # 2. 「日付/時間」または「日付/時刻」カラムから取得
                if time_str == "時刻不明":
                    datetime_str = record.get('日付/時間') or record.get('日付/時刻') or ""
                    if datetime_str:
                        try:
                            from datetime import datetime
                            datetime_str_clean = str(datetime_str).strip()
                            if ' ' in datetime_str_clean:
                                try:
                                    dt = datetime.strptime(datetime_str_clean, "%Y/%m/%d %H:%M")
                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    try:
                                        dt = datetime.strptime(datetime_str_clean, "%Y-%m-%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        time_str = datetime_str_clean
                            elif 'T' in datetime_str_clean:
                                try:
                                    if datetime_str_clean.endswith('Z'):
                                        datetime_str_clean = datetime_str_clean[:-1]
                                    if len(datetime_str_clean) >= 19:
                                        dt = datetime.strptime(datetime_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    pass
                        except Exception:
                            pass
                
                # 3. 「仕入れ時刻」または「purchase_time」カラムから取得
                if time_str == "時刻不明":
                    record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                    if record_time:
                        try:
                            from datetime import datetime
                            record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                            if record_date:
                                date_str = str(record_date).strip()
                                if " " in date_str:
                                    date_str = date_str.split(" ")[0]
                                if "T" in date_str:
                                    date_str = date_str.split("T")[0]
                                date_str = date_str.replace("/", "-")
                                datetime_str = f"{date_str} {record_time}"
                                try:
                                    dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    time_str = f"{date_str} {record_time}"
                        except Exception:
                            pass
                
                # 4. created_atから時刻を取得（最後のフォールバック）
                if time_str == "時刻不明":
                    record_created_at = record.get('created_at') or record.get('登録日時') or ""
                    if record_created_at:
                        try:
                            from datetime import datetime
                            if isinstance(record_created_at, str):
                                record_created_at_clean = str(record_created_at).strip()
                                if 'T' in record_created_at_clean:
                                    if record_created_at_clean.endswith('Z'):
                                        record_created_at_clean = record_created_at_clean[:-1]
                                    if len(record_created_at_clean) >= 19:
                                        dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                elif ' ' in record_created_at_clean:
                                    if len(record_created_at_clean) >= 19:
                                        dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                        except Exception:
                            pass
                
                # 5. SKUコードから日付を抽出して時刻を推測（最後のフォールバック）
                if time_str == "時刻不明":
                    # SKUコードから日付を抽出（例: hmk-20251213-used2-033 → 20251213）
                    sku_code = record.get('SKU') or record.get('sku', '')
                    if sku_code:
                        import re
                        # YYYYMMDD形式の日付を抽出
                        date_match = re.search(r'(\d{8})', str(sku_code))
                        if date_match:
                            date_str = date_match.group(1)
                            try:
                                from datetime import datetime
                                # YYYYMMDD形式をYYYY/MM/DDに変換
                                date_obj = datetime.strptime(date_str, "%Y%m%d")
                                # レシートの時刻があれば使用、なければ日付のみ
                                receipt_time = receipt_data.get('purchase_time', '') if receipt_data else ''
                                if receipt_time:
                                    time_str = f"{date_obj.strftime('%Y/%m/%d')} {receipt_time}"
                                else:
                                    time_str = date_obj.strftime('%Y/%m/%d')
                            except Exception:
                                pass
                
                return time_str
            
            # 候補SKUを読み込み
            def load_candidate_skus():
                existing_skus: set[str] = set()
                for i in range(linked_skus_list.count()):
                    item = linked_skus_list.item(i)
                    if not item:
                        continue
                    sku = item.data(Qt.UserRole)
                    if sku:
                        existing_skus.add(str(sku))
                    else:
                        text = item.text()
                        if " - " in text:
                            existing_skus.add(text.split(" - ")[0].strip())
                        elif text.strip():
                            existing_skus.add(text.strip())

                receipt_ctx = dict(receipt_data or {})
                purchase_date_str = receipt_ctx.get("purchase_date")
                purchase_time_str = receipt_ctx.get("purchase_time") or ""
                store_code_val = receipt_ctx.get("store_code") or ""
                try:
                    date_val = date_edit.date()
                    if date_val.isValid():
                        purchase_date_str = date_val.toString("yyyy-MM-dd")
                    purchase_time_str = time_edit.text().strip()
                    store_code_val = store_code_display.text().strip()
                except (NameError, AttributeError):
                    pass

                self._populate_candidate_sku_list(
                    candidate_skus_list,
                    receipt_ctx,
                    existing_skus,
                    purchase_date_str=purchase_date_str,
                    purchase_time_str=purchase_time_str,
                    store_code=store_code_val,
                )

            load_candidate_skus()
            
            # レシートIDが変更されたときに候補SKUを再読み込み
            
            # SKU呼び出しボタン（同じ日付のSKUを時間が近い順から表示）
            fetch_sku_btn = QPushButton("SKU呼び出し")
            fetch_sku_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    padding: 6px 12px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
            """)
            
            def fetch_skus_by_date(show_message=True):
                """同じ日付のSKUを時間が近い順から取得して候補リストに表示
                
                Args:
                    show_message: Trueの場合、メッセージボックスを表示する（デフォルト: True）
                """
                candidate_skus_list.clear()
                if not self.product_widget:
                    if show_message:
                        QMessageBox.warning(None, "警告", "仕入DBへの参照がありません。")
                    return

                purchase_records = self._get_purchase_records()
                if not purchase_records:
                    if show_message:
                        QMessageBox.warning(None, "警告", "仕入DBにデータがありません。")
                    return
                
                # レシートの日付を取得（日付フィールドから最新の値を取得）
                # まず、日付フィールドから直接取得を試みる（クロージャ経由でアクセス可能）
                purchase_date = ''
                purchase_time = ''
                try:
                    # 日付フィールドから最新の日付を取得
                    date_val = date_edit.date()
                    if date_val.isValid():
                        purchase_date = date_val.toString("yyyy/MM/dd")
                    # 時刻フィールドから最新の時刻を取得
                    purchase_time = time_edit.text().strip()
                except (NameError, AttributeError):
                    # フィールドから取得できない場合は、receipt_dataから取得
                    purchase_date = receipt_data.get('purchase_date', '') if receipt_data else ''
                    purchase_time = receipt_data.get('purchase_time', '') if receipt_data else ''
                
                if not purchase_date:
                    if show_message:
                        QMessageBox.warning(None, "警告", "レシートの日付が設定されていません。")
                    return
                
                # レシートの店舗コード（優先表示用）を取得
                # まず、レシート情報編集画面の店舗コードフィールドから直接取得を試みる
                # store_code_displayは_show_image_popup関数内のローカル変数なので、クロージャ経由でアクセス可能
                receipt_store_code_raw = ''
                try:
                    # クロージャ内でstore_code_displayを直接参照（Pythonのクロージャの仕組みにより可能）
                    receipt_store_code_raw = store_code_display.text().strip()
                except (NameError, AttributeError):
                    # store_code_displayが存在しない場合は、receipt_dataから取得
                    receipt_store_code_raw = receipt_data.get('store_code', '') if receipt_data else ''
                
                # フィールドから取得できない場合は、receipt_dataから取得
                if not receipt_store_code_raw:
                    receipt_store_code_raw = receipt_data.get('store_code', '') if receipt_data else ''
                
                receipt_store_code_clean = str(receipt_store_code_raw).strip()
                if " " in receipt_store_code_clean:
                    receipt_store_code_clean = receipt_store_code_clean.split(" ")[0]
                
                # 店舗マスタから正規の店舗コード（store_code）を取得して比較に使う
                receipt_store_code_canon = receipt_store_code_clean
                try:
                    if receipt_store_code_clean:
                        store = self.store_db.get_store_by_code(receipt_store_code_clean)
                        if store:
                            receipt_store_code_canon = (store.get("store_code") or receipt_store_code_clean).strip() or receipt_store_code_clean
                except Exception:
                    pass
                
                # デバッグ: 店舗コードの取得状況を確認
                logger.debug(f"店舗コード取得: raw={receipt_store_code_raw}, clean={receipt_store_code_clean}, canon={receipt_store_code_canon}")
                
                # レシートの日時をdatetimeオブジェクトに変換（比較用）
                receipt_datetime = None
                if purchase_time:
                    try:
                        from datetime import datetime
                        date_str = purchase_date.replace("/", "-")
                        datetime_str = f"{date_str} {purchase_time}"
                        receipt_datetime = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                    except Exception:
                        pass
                
                # レシートの日付を正規化
                try:
                    from datetime import datetime
                    receipt_date_obj = None
                    if "/" in purchase_date:
                        receipt_date_obj = datetime.strptime(purchase_date, "%Y/%m/%d").date()
                    elif "-" in purchase_date:
                        receipt_date_obj = datetime.strptime(purchase_date[:10], "%Y-%m-%d").date()
                except Exception:
                    receipt_date_obj = None
                
                # 同じ日付のSKUを取得（時間差も計算）
                candidate_skus_with_time = []
                existing_skus = set()
                # 既に紐付けられているSKUを取得
                for i in range(linked_skus_list.count()):
                    item = linked_skus_list.item(i)
                    if item:
                        sku = item.data(Qt.UserRole)
                        if sku:
                            existing_skus.add(sku)
                
                for record in purchase_records:
                    record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                    if not record_date:
                        continue
                    
                    # 仕入DBの日付を正規化
                    try:
                        from datetime import datetime
                        record_date_str = str(record_date).strip()
                        if " " in record_date_str:
                            record_date_str = record_date_str.split(" ")[0]
                        if "T" in record_date_str:
                            record_date_str = record_date_str.split("T")[0]
                        
                        record_date_obj = None
                        if "/" in record_date_str:
                            record_date_obj = datetime.strptime(record_date_str[:10].replace("/", "-"), "%Y-%m-%d").date()
                        elif "-" in record_date_str:
                            record_date_obj = datetime.strptime(record_date_str[:10], "%Y-%m-%d").date()
                        
                        # 日付が一致しない場合はスキップ
                        if receipt_date_obj and record_date_obj and receipt_date_obj != record_date_obj:
                            continue
                        
                        # 日付が一致するか確認
                        date_matches = False
                        if receipt_date_obj and record_date_obj:
                            date_matches = (receipt_date_obj == record_date_obj)
                        else:
                            normalized_receipt_date = purchase_date.replace("-", "/")
                            normalized_record_date = str(record_date).replace("-", "/")
                            date_matches = normalized_receipt_date[:10] in normalized_record_date[:10]
                        
                        if date_matches:
                            sku = record.get('SKU') or record.get('sku', '')
                            if not sku or not sku.strip() or sku.strip() in existing_skus:
                                continue
                            
                            sku = sku.strip()
                            
                            # 時刻差を計算（レシート時刻に近い順にソートするため）
                            time_diff_seconds = float('inf')  # 時刻がない場合は最後に表示
                            record_datetime = None
                            
                            # 仕入DBの時刻を取得
                            record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                            if not record_time:
                                # created_atから時刻を取得
                                record_created_at = record.get('created_at') or record.get('登録日時') or ""
                                if record_created_at:
                                    try:
                                        from datetime import datetime
                                        if isinstance(record_created_at, str):
                                            record_created_at_clean = str(record_created_at).strip()
                                            if 'T' in record_created_at_clean:
                                                if record_created_at_clean.endswith('Z'):
                                                    record_created_at_clean = record_created_at_clean[:-1]
                                                if len(record_created_at_clean) >= 19:
                                                    record_datetime = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                            elif ' ' in record_created_at_clean:
                                                if len(record_created_at_clean) >= 19:
                                                    record_datetime = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                        else:
                                            record_datetime = record_created_at
                                    except Exception:
                                        pass
                            else:
                                # 仕入れ時刻からdatetimeオブジェクトを作成
                                try:
                                    from datetime import datetime
                                    date_str = str(record_date).strip()
                                    if " " in date_str:
                                        date_str = date_str.split(" ")[0]
                                    if "T" in date_str:
                                        date_str = date_str.split("T")[0]
                                    date_str = date_str.replace("/", "-")
                                    datetime_str = f"{date_str} {record_time}"
                                    record_datetime = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                except Exception:
                                    pass
                            
                            # 時刻差を計算
                            if receipt_datetime and record_datetime:
                                time_diff = abs((receipt_datetime - record_datetime).total_seconds())
                                time_diff_seconds = time_diff
                            
                            # SKU情報を取得
                            price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                            try:
                                price = float(price) if price else 0
                            except (ValueError, TypeError):
                                price = 0
                            quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                            try:
                                quantity = float(quantity) if quantity else 1
                            except (ValueError, TypeError):
                                quantity = 1
                            total_amount = price * quantity
                            
                            # 商品名を取得
                            product_name = record.get('商品名') or record.get('product_name') or ''
                            
                            # 店舗コードを取得（新しい店舗コードを優先、なければ旧仕入先コードをフォールバック）
                            raw_store_code = (
                                record.get('店舗コード')
                                or record.get('store_code')
                                or record.get('仕入先')
                                or ''
                            )
                            # 店舗コードのクリーン版（比較用）
                            record_store_code_clean = str(raw_store_code).strip()
                            if " " in record_store_code_clean:
                                record_store_code_clean = record_store_code_clean.split(" ")[0]
                            # 店舗マスタから正規の店舗コード（store_code）を取得
                            record_store_code_canon = record_store_code_clean
                            try:
                                if record_store_code_clean:
                                    r_store = self.store_db.get_store_by_code(record_store_code_clean)
                                    if r_store:
                                        record_store_code_canon = (r_store.get("store_code") or record_store_code_clean).strip() or record_store_code_clean
                            except Exception:
                                pass
                            # 表示ラベル（コード + 店舗名）を生成
                            # ラベルにはクリーンなコード（旧コード含む）から、店舗マスタ経由で新店舗コードを反映する
                            store_label = self._format_store_code_label(record_store_code_clean, "")
                            
                            # SKU文字列内に店舗コードが含まれているかをチェック
                            # SKU形式: YYYYMMDD-STORE_CODE-NNN の形式を想定
                            # 例: 20260117-OF-08-027 の場合、店舗コード OF-08 が含まれている
                            sku_contains_store_code = False
                            if receipt_store_code_canon and sku:
                                # 店舗コードを正規化（大文字小文字を無視、ハイフンの有無を考慮）
                                receipt_code_normalized = receipt_store_code_canon.strip().upper()
                                
                                # 方法1: SKU文字列内に店舗コードが直接含まれているかチェック（大文字小文字を無視）
                                sku_upper = sku.upper()
                                if receipt_code_normalized in sku_upper:
                                    sku_contains_store_code = True
                                else:
                                    # 方法2: SKUを分割して、日付と連番の間の部分をチェック
                                    sku_parts = sku.split('-')
                                    if len(sku_parts) >= 3:
                                        # 日付（最初の部分）と連番（最後の部分）の間の部分を結合
                                        # 例: 20260117-OF-08-027 → ['20260117', 'OF', '08', '027']
                                        # 中間部分: 'OF-08' を生成
                                        middle_parts = sku_parts[1:-1]  # 最初と最後を除く
                                        if middle_parts:
                                            middle_combined = '-'.join(middle_parts)
                                            middle_combined_upper = middle_combined.upper()
                                            
                                            # 店舗コードと一致するか、または店舗コードが含まれているかチェック
                                            if receipt_code_normalized == middle_combined_upper or receipt_code_normalized in middle_combined_upper:
                                                sku_contains_store_code = True
                                            else:
                                                # ハイフンなしで比較（例: OF08）
                                                receipt_code_no_hyphen = receipt_code_normalized.replace('-', '')
                                                middle_no_hyphen = ''.join(middle_parts).upper()
                                                if receipt_code_no_hyphen == middle_no_hyphen or receipt_code_no_hyphen in middle_no_hyphen:
                                                    sku_contains_store_code = True
                                            
                                            # 追加チェック: 店舗コードの各部分が中間部分に含まれているか
                                            if not sku_contains_store_code:
                                                receipt_code_parts = receipt_code_normalized.split('-')
                                                if len(receipt_code_parts) >= 2:
                                                    # 例: OF-08 → ['OF', '08'] が ['OF', '08'] に含まれているか
                                                    all_parts_match = all(
                                                        any(part.upper() == middle_part.upper() for middle_part in middle_parts)
                                                        for part in receipt_code_parts
                                                    )
                                                    if all_parts_match:
                                                        sku_contains_store_code = True
                            
                            # レシートの正規店舗コードと、仕入レコードの正規店舗コードが一致するかで優先度を決定
                            is_same_store = bool(
                                receipt_store_code_canon
                                and record_store_code_canon
                                and receipt_store_code_canon == record_store_code_canon
                            )
                            
                            candidate_skus_with_time.append({
                                'sku': sku,
                                'time_diff': time_diff_seconds,
                                'price': total_amount,
                                'product_name': product_name,
                                'store_label': store_label,
                                # SKU文字列内に店舗コードが含まれている場合は最優先
                                'sku_contains_store_code': sku_contains_store_code,
                                # レシートの正規店舗コードと、仕入レコードの正規店舗コードが一致するかで優先度を決定
                                'is_same_store': is_same_store,
                                'record_datetime': record_datetime.strftime("%Y/%m/%d %H:%M") if record_datetime else "時刻不明"
                            })
                    except Exception:
                        continue
                
                # 並び順:
                #  1. SKU文字列内に店舗コードが含まれているSKUを最優先（一番上）
                #  2. レシートと同じ店舗コードのSKUを次に優先
                #  3. その中で時間差が小さい順（レシート時刻に近い順）
                
                # デバッグ: 店舗コードとSKUのマッチング状況を確認
                if receipt_store_code_canon:
                    logger.debug(f"レシート店舗コード: {receipt_store_code_canon}")
                    matched_skus = [x['sku'] for x in candidate_skus_with_time if x.get('sku_contains_store_code')]
                    if matched_skus:
                        logger.debug(f"店舗コードを含むSKU: {matched_skus}")
                    else:
                        logger.debug(f"店舗コードを含むSKUが見つかりませんでした。候補数: {len(candidate_skus_with_time)}")
                        # 最初の数件のSKUをログ出力
                        for i, item in enumerate(candidate_skus_with_time[:5]):
                            logger.debug(f"  候補{i+1}: {item['sku']}, 店舗コード含む: {item.get('sku_contains_store_code')}")
                
                candidate_skus_with_time.sort(
                    key=lambda x: (
                        0 if x.get('sku_contains_store_code') else 1,  # SKU内に店舗コードが含まれている場合は最優先
                        0 if x.get('is_same_store') else 1,  # 次に店舗コードが一致するもの
                        x['time_diff']  # 最後に時間差でソート
                    )
                )
                
                # 候補リストに表示
                for sku_info in candidate_skus_with_time:
                    sku = sku_info['sku']
                    price = sku_info['price']
                    product_name = sku_info['product_name']
                    store_label = sku_info['store_label']
                    time_str = sku_info['record_datetime']
                    
                    # 表示テキストを作成
                    display_parts = [sku]
                    if store_label:
                        display_parts.append(f"[{store_label}]")
                    if product_name:
                        # 商品名が長い場合は切り詰め
                        name_display = product_name[:30] + "..." if len(product_name) > 30 else product_name
                        display_parts.append(name_display)
                    display_parts.append(f"¥{int(price):,}")
                    display_parts.append(f"({time_str})")
                    
                    display_text = " - ".join(display_parts)
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.UserRole, sku)  # SKUをUserRoleに保存
                    candidate_skus_list.addItem(item)
                
                if show_message:
                    if candidate_skus_list.count() == 0:
                        QMessageBox.information(None, "情報", f"日付 {purchase_date} のSKUが見つかりませんでした。")
                    else:
                        QMessageBox.information(None, "情報", f"{candidate_skus_list.count()} 件のSKU候補を表示しました。")
            
            fetch_sku_btn.clicked.connect(fetch_skus_by_date)
            sku_layout.addWidget(fetch_sku_btn)
            
            # 日付変更時にSKUマッチングを自動実行（候補SKUリストを更新、メッセージは表示しない）
            date_edit.dateChanged.connect(lambda: fetch_skus_by_date(show_message=False))
            
            # SKU追加ボタン
            add_sku_btn = QPushButton("選択SKUを追加")
            add_sku_btn.clicked.connect(lambda: self._add_skus_to_list(candidate_skus_list, linked_skus_list, total_edit))
            sku_layout.addWidget(add_sku_btn)
            
            # SKU直接入力エリア
            sku_input_layout = QHBoxLayout()
            sku_input_label = QLabel("SKU直接入力:")
            sku_input_layout.addWidget(sku_input_label)
            
            sku_input_edit = QLineEdit()
            sku_input_edit.setPlaceholderText("SKUを入力（カンマ区切りで複数可）")
            sku_input_edit.returnPressed.connect(lambda: self._add_sku_by_input(sku_input_edit, linked_skus_list, total_edit, sku_info_map))
            sku_input_layout.addWidget(sku_input_edit)
            
            sku_input_btn = QPushButton("追加")
            sku_input_btn.clicked.connect(lambda: self._add_sku_by_input(sku_input_edit, linked_skus_list, total_edit, sku_info_map))
            sku_input_layout.addWidget(sku_input_btn)
            
            sku_layout.addLayout(sku_input_layout)
            
            right_layout.addWidget(sku_group)
            
            # 保存ボタン
            save_btn = QPushButton("変更を保存")
            save_btn.setStyleSheet("""
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
            
            def save_changes():
                """変更を保存"""
                save_btn.setEnabled(False)
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    updates = {}
                    linked_skus: List[str] = []
                    sku_price_updates: Dict[str, int] = {}
                    save_snapshot = False
                    affected_skus: set[str] = set()
                    purchase_records: List[Dict[str, Any]] = []
                    sku_to_record: Dict[str, Dict[str, Any]] = {}
                    if self.product_widget:
                        purchase_records = list(
                            getattr(self.product_widget, "purchase_all_records", []) or []
                        )
                        sku_to_record = self._build_purchase_sku_index(purchase_records)
                
                    # 種別と科目
                    account_title = account_title_combo.currentText()
                    if account_title:
                        updates['account_title'] = account_title
                
                    # 科目が「仕入」かどうかを判定
                    is_purchase = account_title and account_title.strip() == "仕入"
                
                    # 日付
                    date = date_edit.date()
                    updates['purchase_date'] = date.toString("yyyy/MM/dd")
                
                    # 時刻
                    time_str = time_edit.text().strip()
                    if time_str:
                        updates['purchase_time'] = time_str
                
                    # 店舗名（プルダウンから選択した店舗コード＋店舗名）
                    selected_store_code = store_name_combo.currentData()
                    selected_store_label = store_name_combo.currentText()
                    if selected_store_code:
                        updates['store_code'] = selected_store_code
                        # 店舗名（生）は店舗マスタまたは経費先から取得
                        store_name_raw = None
                        try:
                            store = self.store_db.get_store_by_code(selected_store_code)
                            if store:
                                store_name_raw = (store.get('store_name') or '').strip()
                            if not store_name_raw:
                                dest = self.store_db.get_expense_destination_by_code(selected_store_code)
                                if dest:
                                    store_name_raw = (dest.get('name') or '').strip()
                            if not store_name_raw:
                                # ラベルから店舗名を抽出（「CODE 店舗名」形式 → 店舗名部分）
                                if selected_store_label.startswith(selected_store_code):
                                    store_name_raw = selected_store_label[len(selected_store_code):].strip()
                                else:
                                    store_name_raw = selected_store_label.strip()
                            if store_name_raw:
                                updates['store_name_raw'] = store_name_raw
                        except Exception:
                            if selected_store_label.startswith(selected_store_code):
                                updates['store_name_raw'] = selected_store_label[len(selected_store_code):].strip()
                            else:
                                updates['store_name_raw'] = selected_store_label.strip()
                
                    # 電話番号
                    phone = phone_edit.text().strip()
                    if phone:
                        updates['phone_number'] = phone
                
                    # 登録番号
                    registration_number = registration_edit.text().strip()
                    if registration_number:
                        updates['registration_number'] = registration_number
                
                    # 合計
                    try:
                        total = int(total_edit.text()) if total_edit.text().strip() else None
                        if total is not None:
                            updates['total_amount'] = total
                    except ValueError:
                        pass
                
                    # 値引
                    try:
                        discount = int(discount_edit.text()) if discount_edit.text().strip() else None
                        if discount is not None:
                            updates['discount_amount'] = discount
                    except ValueError:
                        pass
                
                    # 紐付けSKUと差額計算は「仕入」科目の場合のみ処理
                    if is_purchase:
                        # 紐付けSKU（UserRoleからSKUを取得）
                        linked_skus = []
                        sku_price_updates = {}  # SKUと価格のマッピング（仕入DB更新用）
                        for i in range(linked_skus_list.count()):
                            item = linked_skus_list.item(i)
                            if item:
                                sku = item.data(Qt.UserRole)
                                if not sku:
                                    # UserRoleがない場合は表示テキストからSKUを抽出
                                    text = item.text()
                                    if " - " in text:
                                        sku = text.split(" - ")[0].strip()
                                    else:
                                        sku = text.strip()
                            
                                if sku:
                                    sku = str(sku).strip()
                                    linked_skus.append(sku)
                                    affected_skus.add(sku)
                                    # 価格を取得（UserRole + 1に保存されている場合）
                                    new_price = item.data(Qt.UserRole + 1)
                                    if new_price is None:
                                        # UserRole + 1にない場合は表示テキストから抽出
                                        text = item.text()
                                        if " - ¥" in text:
                                            try:
                                                price_str = text.split(" - ¥")[1].replace(",", "").strip()
                                                new_price = int(price_str)
                                            except (ValueError, IndexError):
                                                new_price = None
                                    
                                    if new_price is not None:
                                        sku_price_updates[sku] = new_price
                    
                        updates['linked_skus'] = ','.join(linked_skus) if linked_skus else None
                    
                        # 差額を再計算（表示テキストから直接合計金額を取得：再計算後の価格を反映）
                        sku_total = 0
                        for i in range(linked_skus_list.count()):
                            item = linked_skus_list.item(i)
                            if item:
                                # 表示テキストから合計金額を抽出（再計算後の価格が反映されている）
                                text = item.text()
                                total_amount = 0
                            
                                if " - ¥" in text:
                                    try:
                                        # 「 - ¥金額 - (時刻)」または「 - ¥金額」形式から金額を抽出
                                        price_part = text.split(" - ¥")[1]
                                        # 時刻部分を除去（「 - (時刻)」がある場合）
                                        if " - (" in price_part:
                                            price_str = price_part.split(" - (")[0].replace(",", "").strip()
                                        else:
                                            price_str = price_part.replace(",", "").strip()
                                        total_amount = int(price_str)
                                    except (ValueError, IndexError):
                                        total_amount = 0
                                elif "¥" in text:
                                    # フォールバック: 「¥金額」形式を直接検索
                                    try:
                                        price_parts = text.split("¥")
                                        if len(price_parts) > 1:
                                            price_str = price_parts[1].split()[0].replace(",", "").strip()
                                            total_amount = int(price_str)
                                    except (ValueError, IndexError):
                                        total_amount = 0
                            
                                sku_total += total_amount
                    
                        # レシートの合計金額を取得
                        receipt_total = updates.get('total_amount')
                        if receipt_total is None:
                            try:
                                receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                            except ValueError:
                                receipt_total = 0
                    
                        # 値引きを考慮
                        discount = updates.get('discount_amount', 0)
                        if discount is None:
                            discount = 0
                        receipt_total_after_discount = receipt_total - discount
                    
                        # 差額を計算（SKU合計 - レシート合計（値引き後））
                        difference = sku_total - receipt_total_after_discount
                        # 実差額を保存（一覧では ±30円以内を「OK」表示。仕入DBの金額は変更しない）
                        updates['price_difference'] = int(difference)
                    else:
                        # 科目が「仕入」以外の場合は紐付けSKUをクリアし、差額は0（OK表示）にする
                        updates['linked_skus'] = None
                        updates['price_difference'] = 0
                
                    # 仕入DBの価格を更新し、見込み利益・損益分岐点・利益率・ROIを再計算（科目が「仕入」かつポリシー許可時のみ）
                    if (
                        RECEIPT_MUTATES_PURCHASE_DB_PRICE
                        and is_purchase
                        and sku_price_updates
                        and self.product_widget
                    ):
                        try:
                            updated_count = 0
                            pending_product_upserts: Dict[str, Dict[str, Any]] = {}
                            for sku, new_price in sku_price_updates.items():
                                record = sku_to_record.get(sku)
                                if not record:
                                    continue
                                # 仕入れ価格を更新
                                record['仕入れ価格'] = new_price
                            
                                # 見込み利益・損益分岐点・利益率・ROIを再計算
                                planned_price = record.get('販売予定価格') or record.get('planned_price') or 0
                                try:
                                    planned_price = float(planned_price) if planned_price else 0
                                except (ValueError, TypeError):
                                    planned_price = 0
                            
                                # 見込み利益 = 販売予定価格 - 仕入れ価格
                                expected_profit = planned_price - new_price if planned_price > 0 else 0
                                record['見込み利益'] = expected_profit
                            
                                other_cost = record.get('その他費用') or record.get('other_cost') or 0
                                try:
                                    other_cost = float(other_cost) if other_cost else 0
                                except (ValueError, TypeError):
                                    other_cost = 0
                                be = compute_break_even_for_record(record)
                                if be is not None:
                                    record["損益分岐点"] = round(be, 2)
                                else:
                                    record["損益分岐点"] = new_price + other_cost
                            
                                # 利益率 = (見込み利益 / 販売予定価格) * 100
                                if planned_price > 0:
                                    expected_margin = (expected_profit / planned_price) * 100
                                else:
                                    expected_margin = 0.0
                                record['想定利益率'] = round(expected_margin, 2)
                            
                                # ROI = (見込み利益 / 仕入れ価格) * 100
                                if new_price > 0:
                                    expected_roi = (expected_profit / new_price) * 100
                                else:
                                    expected_roi = 0.0
                                record['想定ROI'] = round(expected_roi, 2)
                            
                                # ProductDatabase 更新は後でまとめて実行
                                if hasattr(self.product_widget, 'db'):
                                    existing = self.product_widget.db.get_by_sku(sku)
                                    if existing:
                                        db_record = dict(existing)
                                        db_record['purchase_price'] = new_price
                                        pending_product_upserts[sku] = db_record
                                    else:
                                        pending_product_upserts[sku] = {
                                            'sku': sku,
                                            'purchase_price': new_price,
                                        }
                            
                                updated_count += 1

                            if pending_product_upserts and hasattr(self.product_widget, 'db'):
                                for sku, db_record in pending_product_upserts.items():
                                    try:
                                        self.product_widget.db.upsert(db_record)
                                    except Exception as e:
                                        QMessageBox.warning(
                                            self,
                                            "警告",
                                            f"SKU {sku} のDB更新中にエラーが発生しました: {str(e)}",
                                        )

                            if updated_count > 0:
                                save_snapshot = True
                        except Exception as e:
                            QMessageBox.warning(self, "警告", f"仕入DBの更新中にエラーが発生しました: {str(e)}")

                    # 店舗マスタ側に登録番号を反映（store_code があり、まだ登録番号が空の場合）
                    try:
                        selected_store_code = updates.get('store_code') or receipt_data.get('store_code') or ''
                        reg_no = updates.get('registration_number') or receipt_data.get('registration_number') or ''
                        if selected_store_code and reg_no:
                            store = self.store_db.get_store_by_code(selected_store_code)
                            if store and not store.get('registration_number'):
                                # 既存の登録番号が空のときのみ更新
                                self.store_db.update_registration_number(store.get('id'), reg_no)
                    except Exception as e:
                        print(f"[レシート情報編集] 登録番号の店舗マスタ反映エラー: {e}")
                
                    # レシート画像を仕入DBに反映（科目が「仕入」でSKUが紐付けられている場合）
                    if is_purchase and linked_skus and self.product_widget:
                        try:
                            # レシート情報から画像ファイル名を取得
                            receipt_info = self.receipt_db.get_receipt(receipt_id)
                            if receipt_info:
                                # 画像ファイルパスを取得（original_file_pathを優先、なければfile_path）
                                file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path', '')
                                if file_path:
                                    image_file = Path(file_path)
                                    if image_file.exists():
                                        # ファイル名（拡張子なし）を取得（表示用）
                                        image_file_name = image_file.stem
                                        resolved_path = str(image_file.resolve())
                                    
                                        # 各SKUに対してレシート画像を反映
                                        for sku in linked_skus:
                                            record = sku_to_record.get(sku)
                                            if not record:
                                                continue
                                            record['レシート画像'] = image_file_name
                                            record['レシート画像パス'] = resolved_path
                                            affected_skus.add(sku)
                                        
                                            if hasattr(self.product_widget, 'db'):
                                                product = self.product_widget.db.get_by_sku(sku)
                                                if product:
                                                    product['receipt_id'] = image_file_name
                                                    self.product_widget.db.upsert(product)
                        except Exception as e:
                            QMessageBox.warning(self, "警告", f"レシート画像の反映中にエラーが発生しました: {str(e)}")
                
                    # DB更新
                    if updates and receipt_id:
                        self.receipt_db.update_receipt(receipt_id, updates)
                        if not self._patch_receipt_table_row(receipt_id, updates):
                            self.refresh_receipt_list(offer_date_repair=False)
                        QMessageBox.information(self, "完了", "変更を保存しました。")
                        self._defer_after_receipt_manual_save(
                            affected_skus=sorted(affected_skus),
                            save_snapshot=save_snapshot,
                        )
                        # ウインドウは閉じない（変更を保存しても閉じない）
                    else:
                        QMessageBox.information(self, "情報", "変更がありません。")
                finally:
                    save_btn.setEnabled(True)
                    QApplication.restoreOverrideCursor()
            
            # 再計算ボタンと保存ボタンを横並びに配置
            button_layout = QHBoxLayout()
            
            # 再計算ボタン
            recalc_btn = QPushButton("再計算")
            recalc_btn.setStyleSheet("""
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
            
            def recalculate_prices():
                """再計算ボタンの処理（科目が「仕入」の場合のみ）"""
                # 科目が「仕入」でない場合は処理しない
                current_account_title = account_title_combo.currentText()
                if not current_account_title or current_account_title.strip() != "仕入":
                    QMessageBox.information(self, "情報", "再計算は「仕入」科目の場合のみ使用できます。")
                    return
                
                try:
                    # レシート情報編集エリアの値を取得
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                    discount = int(discount_edit.text()) if discount_edit.text().strip() else 0
                    
                    # 調整後の目標金額 = レシート合計 - 値引き
                    target_total = receipt_total - discount
                    
                    # 仕入DBから価格情報を取得（元の金額を取得するため）
                    sku_price_map = {}
                    if self.product_widget:
                        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                        for record in purchase_records:
                            sku = record.get('SKU') or record.get('sku', '')
                            if sku and sku.strip():
                                sku_price_map[sku.strip()] = record
                    
                    # 現在のSKU価格の合計を計算（仕入DBから元の金額を取得）
                    current_total = 0
                    sku_items = []
                    for i in range(linked_skus_list.count()):
                        item = linked_skus_list.item(i)
                        if item:
                            sku = item.data(Qt.UserRole)
                            if not sku:
                                text = item.text()
                                if " - " in text:
                                    sku = text.split(" - ")[0].strip()
                                else:
                                    sku = text.strip()
                            
                            # 仕入DBから元の金額を取得（仕入れ個数 × 仕入れ価格）
                            total_amount = 0
                            if sku and sku.strip() and sku.strip() in sku_price_map:
                                record = sku_price_map[sku.strip()]
                                # 仕入れ価格を取得
                                price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                                try:
                                    price = float(price) if price else 0
                                except (ValueError, TypeError):
                                    price = 0
                                # 仕入れ個数を取得
                                quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                                try:
                                    quantity = float(quantity) if quantity else 1
                                except (ValueError, TypeError):
                                    quantity = 1
                                # 金額 = 仕入れ個数 × 仕入れ価格
                                total_amount = price * quantity
                            else:
                                # 仕入DBにない場合は表示テキストから取得
                                text = item.text()
                                if " - ¥" in text:
                                    try:
                                        price_str = text.split(" - ¥")[1].replace(",", "").strip()
                                        total_amount = int(price_str)
                                    except (ValueError, IndexError):
                                        total_amount = 0
                            
                            current_total += total_amount
                            sku_items.append((item, sku, total_amount))
                    
                    if not sku_items:
                        QMessageBox.warning(self, "警告", "紐付けSKUがありません。")
                        return
                    
                    # 差額を計算
                    difference = target_total - current_total
                    
                    # 差額が30円以内の場合は最後のSKUで調整
                    # 差額が30円以上の場合は全体の金額の割合で振り分け、端数は最後のSKUで調整
                    new_total_amounts = []
                    
                    if abs(difference) <= 30:
                        # 30円以内：最後のSKUで調整
                        for idx, (item, sku, old_total_amount) in enumerate(sku_items):
                            if idx == len(sku_items) - 1:
                                # 最後のSKUに差額を全て追加
                                new_total_amount = old_total_amount + difference
                            else:
                                # 他のSKUは変更なし
                                new_total_amount = old_total_amount
                            
                            if new_total_amount < 0:
                                new_total_amount = 0
                            new_total_amounts.append((item, sku, new_total_amount))
                    else:
                        # 30円以上：全体の金額の割合で振り分け
                        # 各SKUの現在の金額の割合を計算し、目標金額をその割合で分配
                        ratios = []
                        allocated_amounts = []
                        total_allocated = 0
                        
                        # 各SKUの割合を計算
                        for idx, (item, sku, old_total_amount) in enumerate(sku_items):
                            if current_total > 0:
                                # 各SKUの割合を計算
                                ratio = old_total_amount / current_total
                            else:
                                # 現在の合計が0の場合は均等配分
                                ratio = 1.0 / len(sku_items)
                            
                            ratios.append(ratio)
                            # 目標金額を割合で分配（整数部分）
                            allocated = int(target_total * ratio)
                            allocated_amounts.append(allocated)
                            total_allocated += allocated
                        
                        # 端数を計算（目標金額との差）
                        remainder = target_total - total_allocated
                        
                        # 各SKUの金額を計算
                        for idx, (item, sku, old_total_amount) in enumerate(sku_items):
                            new_total_amount = allocated_amounts[idx]
                            # 最後のSKUに端数を追加
                            if idx == len(sku_items) - 1:
                                new_total_amount += remainder
                            
                            if new_total_amount < 0:
                                new_total_amount = 0
                            new_total_amounts.append((item, sku, new_total_amount))
                    
                    # 各SKUの金額を更新（仕入れ個数 × 仕入れ価格）
                    for item, sku, new_total_amount in new_total_amounts:
                        # 仕入DBから仕入れ個数を取得して、仕入れ価格を計算
                        quantity = 1
                        if sku in sku_price_map:
                            record = sku_price_map[sku]
                            quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                            try:
                                quantity = float(quantity) if quantity else 1
                            except (ValueError, TypeError):
                                quantity = 1
                        
                        # 仕入れ価格 = 合計金額 / 仕入れ個数
                        if quantity > 0:
                            new_price = new_total_amount / quantity
                        else:
                            new_price = new_total_amount
                        
                        # 表示を更新（合計金額を表示）
                        display_text = f"{sku} - ¥{int(new_total_amount):,}"
                        item.setText(display_text)
                        # UserRole + 1に仕入れ価格を保存（仕入DB更新時に使用）
                        item.setData(Qt.UserRole + 1, int(new_price))
                    
                    # 合計と差額を更新（差額は元のレシート合計との差を表示）
                    self._update_sku_total(linked_skus_list, receipt_total)
                    
                    QMessageBox.information(self, "完了", "価格を再計算しました。")
                except Exception as e:
                    QMessageBox.warning(self, "エラー", f"再計算中にエラーが発生しました: {str(e)}")
            
            recalc_btn.clicked.connect(recalculate_prices)
            button_layout.addWidget(recalc_btn)
            
            save_btn.clicked.connect(save_changes)
            button_layout.addWidget(save_btn)
            
            # 閉じるボタンを追加
            close_btn = QPushButton("閉じる")
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: #6c757d;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #5a6268;
                }
            """)
            close_btn.clicked.connect(dialog.close)
            button_layout.addWidget(close_btn)
            
            right_layout.addLayout(button_layout)
            
            right_layout.addStretch()
            main_layout.addWidget(right_widget, 1)  # 編集パネルは1倍の幅

        # モーダルではなくモデルレスで表示（アプリ操作をブロックしない）
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()
    
    def _add_skus_to_list(self, source_list: QListWidget, target_list: QListWidget, total_edit=None):
        """選択されたSKUを追加（価格情報も表示）"""
        selected_items = source_list.selectedItems()
        # 既存のSKUを取得（UserRoleから）
        existing_skus = set()
        for i in range(target_list.count()):
            item = target_list.item(i)
            if item:
                sku = item.data(Qt.UserRole)
                if sku:
                    existing_skus.add(sku)
                else:
                    # UserRoleがない場合は表示テキストからSKUを抽出
                    text = item.text()
                    if " - " in text:
                        sku = text.split(" - ")[0].strip()
                        existing_skus.add(sku)
                    else:
                        existing_skus.add(text.strip())
        
        # 仕入DBから金額情報と時刻情報を取得（仕入れ個数 × 仕入れ価格）
        sku_info_map = {}  # {sku: {'price': total_amount, 'time': time_str}}
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            for record in purchase_records:
                sku = record.get('SKU') or record.get('sku', '')
                if sku and sku.strip():
                    sku = sku.strip()
                    # 仕入れ価格を取得（複数のカラム名に対応）
                    price = record.get('仕入れ価格') or record.get('仕入価格') or record.get('purchase_price') or record.get('cost', 0)
                    try:
                        price = float(price) if price else 0
                    except (ValueError, TypeError):
                        price = 0
                    # 仕入れ個数を取得（複数のカラム名に対応）
                    quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                    try:
                        quantity = float(quantity) if quantity else 1
                    except (ValueError, TypeError):
                        quantity = 1
                    # 金額 = 仕入れ個数 × 仕入れ価格
                    total_amount = price * quantity
                    
                    # 時刻情報を取得
                    time_str = "時刻不明"
                    
                    # 1. 「仕入れ日」カラムから取得（優先）- 「YYYY/MM/DD HH:MM」形式で日付と時刻の両方が含まれる
                    purchase_date_str = record.get('仕入れ日') or record.get('purchase_date') or ""
                    if purchase_date_str:
                        try:
                            from datetime import datetime
                            purchase_date_str_clean = str(purchase_date_str).strip()
                            # 「YYYY/MM/DD HH:MM」形式を想定
                            if ' ' in purchase_date_str_clean:
                                try:
                                    # 「YYYY/MM/DD HH:MM」形式
                                    dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M")
                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    try:
                                        # 「YYYY-MM-DD HH:MM」形式
                                        dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            # 「YYYY/MM/DD HH:MM:SS」形式
                                            dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            try:
                                                # 「YYYY-MM-DD HH:MM:SS」形式
                                                dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M:%S")
                                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                                            except:
                                                # パースできない場合はそのまま使用
                                                time_str = purchase_date_str_clean
                        except Exception as e:
                            print(f"時刻情報取得エラー (仕入れ日): {e}, 値: {purchase_date_str}")
                    
                    # 2. 「日付/時間」または「日付/時刻」カラムから取得
                    if time_str == "時刻不明":
                        datetime_str = record.get('日付/時間') or record.get('日付/時刻') or ""
                        if datetime_str:
                            try:
                                from datetime import datetime
                                datetime_str_clean = str(datetime_str).strip()
                                if ' ' in datetime_str_clean:
                                    try:
                                        dt = datetime.strptime(datetime_str_clean, "%Y/%m/%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            dt = datetime.strptime(datetime_str_clean, "%Y-%m-%d %H:%M")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            time_str = datetime_str_clean
                                elif 'T' in datetime_str_clean:
                                    try:
                                        if datetime_str_clean.endswith('Z'):
                                            datetime_str_clean = datetime_str_clean[:-1]
                                        if len(datetime_str_clean) >= 19:
                                            dt = datetime.strptime(datetime_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        pass
                            except Exception:
                                pass
                    
                    # 3. 「仕入れ時刻」または「purchase_time」カラムから取得
                    if time_str == "時刻不明":
                        record_time = record.get('仕入れ時刻') or record.get('purchase_time') or ""
                        if record_time:
                            try:
                                from datetime import datetime
                                record_date = record.get('仕入れ日') or record.get('purchase_date', '')
                                if record_date:
                                    date_str = str(record_date).strip()
                                    if " " in date_str:
                                        date_str = date_str.split(" ")[0]
                                    if "T" in date_str:
                                        date_str = date_str.split("T")[0]
                                    date_str = date_str.replace("/", "-")
                                    datetime_str = f"{date_str} {record_time}"
                                    try:
                                        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        time_str = f"{date_str} {record_time}"
                            except Exception:
                                pass
                    
                    # 4. created_atから時刻を取得（最後のフォールバック）
                    if time_str == "時刻不明":
                        record_created_at = record.get('created_at') or record.get('登録日時') or ""
                        if record_created_at:
                            try:
                                from datetime import datetime
                                if isinstance(record_created_at, str):
                                    record_created_at_clean = str(record_created_at).strip()
                                    if 'T' in record_created_at_clean:
                                        if record_created_at_clean.endswith('Z'):
                                            record_created_at_clean = record_created_at_clean[:-1]
                                        if len(record_created_at_clean) >= 19:
                                            dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%dT%H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    elif ' ' in record_created_at_clean:
                                        if len(record_created_at_clean) >= 19:
                                            dt = datetime.strptime(record_created_at_clean[:19], "%Y-%m-%d %H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                            except Exception:
                                pass
                    
                    sku_info_map[sku] = {
                        'price': total_amount,
                        'time': time_str
                    }
        
        for item in selected_items:
            # UserRoleからSKUを取得（優先）
            sku = item.data(Qt.UserRole)
            if not sku:
                # UserRoleがない場合は表示テキストからSKUを抽出
                text = item.text().strip()
                if " - " in text:
                    # 「SKU - [店舗コード] - 商品名 - ¥金額 - (時刻)」形式からSKUを抽出
                    sku = text.split(" - ")[0].strip()
                else:
                    sku = text.strip()
            
            if sku and sku not in existing_skus:
                # 候補リストの表示テキストから価格と時刻を抽出（フォールバック）
                source_text = item.text()
                extracted_price = 0
                extracted_time = "時刻不明"
                
                # 表示テキストから価格を抽出（「¥金額」形式）
                if "¥" in source_text:
                    try:
                        price_parts = source_text.split("¥")
                        if len(price_parts) > 1:
                            price_str = price_parts[1].split()[0].replace(",", "").strip()
                            extracted_price = int(price_str)
                    except (ValueError, IndexError):
                        pass
                
                # 表示テキストから時刻を抽出（「(時刻)」形式）
                if "(" in source_text and ")" in source_text:
                    try:
                        time_start = source_text.rfind("(")
                        time_end = source_text.rfind(")")
                        if time_start < time_end:
                            extracted_time = source_text[time_start+1:time_end]
                    except Exception:
                        pass
                
                # 仕入DBから取得した情報を優先（なければ表示テキストから抽出した値を使用）
                sku_info = sku_info_map.get(sku, {})
                total_amount = sku_info.get('price', extracted_price)
                time_str = sku_info.get('time', extracted_time)
                
                # 表示テキストを作成
                if total_amount > 0:
                    display_text = f"{sku} - ¥{int(total_amount):,} - ({time_str})"
                else:
                    display_text = f"{sku} - 価格不明 - ({time_str})"
                
                # リストに追加
                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, sku)  # SKUをUserRoleに保存
                target_list.addItem(list_item)
                existing_skus.add(sku)
        
        # 合計金額を更新
        receipt_total = None
        if total_edit:
            try:
                receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
            except ValueError:
                receipt_total = 0
        self._update_sku_total(target_list, receipt_total)
    
    def _add_sku_by_input(self, sku_input_edit: QLineEdit, linked_skus_list: QListWidget, total_edit, sku_info_map: dict):
        """直接入力されたSKUを仕入DBから検索して追加"""
        sku_text = sku_input_edit.text().strip()
        if not sku_text:
            QMessageBox.warning(self, "警告", "SKUを入力してください。")
            return
        
        # カンマ区切りで複数SKUを処理
        input_skus = [sku.strip() for sku in sku_text.split(',') if sku.strip()]
        if not input_skus:
            QMessageBox.warning(self, "警告", "有効なSKUが入力されていません。")
            return
        
        # 既存のSKUを取得（重複チェック用）
        existing_skus = set()
        for i in range(linked_skus_list.count()):
            item = linked_skus_list.item(i)
            if item:
                sku = item.data(Qt.UserRole)
                if sku:
                    existing_skus.add(sku)
        
        added_count = 0
        not_found_skus = []
        
        # 仕入DBからSKUを検索
        if not self.product_widget:
            QMessageBox.warning(self, "警告", "仕入DBへの参照がありません。")
            return
        
        purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
        
        for input_sku in input_skus:
            # 重複チェック
            if input_sku in existing_skus:
                continue
            
            # 仕入DBから該当SKUを検索
            found_record = None
            for record in purchase_records:
                record_sku = record.get('SKU') or record.get('sku', '')
                if record_sku and record_sku.strip() == input_sku:
                    found_record = record
                    break
            
            if found_record:
                # 仕入れ価格を取得
                price = found_record.get('仕入れ価格') or found_record.get('仕入価格') or found_record.get('purchase_price') or found_record.get('cost', 0)
                try:
                    price = float(price) if price else 0
                except (ValueError, TypeError):
                    price = 0
                
                # 仕入れ個数を取得
                quantity = found_record.get('仕入れ個数') or found_record.get('仕入個数') or found_record.get('quantity') or found_record.get('数量', 1)
                try:
                    quantity = float(quantity) if quantity else 1
                except (ValueError, TypeError):
                    quantity = 1
                
                # 金額 = 仕入れ個数 × 仕入れ価格
                total_amount = price * quantity
                
                # 時刻情報を取得（sku_info_mapと同じロジック）
                time_str = "時刻不明"
                purchase_date_str = found_record.get('仕入れ日') or found_record.get('purchase_date') or ""
                if purchase_date_str:
                    try:
                        from datetime import datetime
                        purchase_date_str_clean = str(purchase_date_str).strip()
                        if ' ' in purchase_date_str_clean:
                            try:
                                dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M")
                                time_str = dt.strftime("%Y/%m/%d %H:%M")
                            except:
                                try:
                                    dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M")
                                    time_str = dt.strftime("%Y/%m/%d %H:%M")
                                except:
                                    try:
                                        dt = datetime.strptime(purchase_date_str_clean, "%Y/%m/%d %H:%M:%S")
                                        time_str = dt.strftime("%Y/%m/%d %H:%M")
                                    except:
                                        try:
                                            dt = datetime.strptime(purchase_date_str_clean, "%Y-%m-%d %H:%M:%S")
                                            time_str = dt.strftime("%Y/%m/%d %H:%M")
                                        except:
                                            time_str = purchase_date_str_clean
                    except Exception:
                        pass
                
                # 表示テキストを作成
                if total_amount > 0:
                    display_text = f"{input_sku} - ¥{int(total_amount):,} - ({time_str})"
                else:
                    display_text = f"{input_sku} - 価格不明 - ({time_str})"
                
                # リストに追加
                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, input_sku)
                linked_skus_list.addItem(list_item)
                existing_skus.add(input_sku)
                added_count += 1
                
                # sku_info_mapにも追加（後で合計計算に使用）
                if input_sku not in sku_info_map:
                    sku_info_map[input_sku] = {
                        'price': total_amount,
                        'time': time_str
                    }
            else:
                # 仕入DBに見つからない場合は、価格不明として追加
                display_text = f"{input_sku} - 価格不明 - (時刻不明)"
                list_item = QListWidgetItem(display_text)
                list_item.setData(Qt.UserRole, input_sku)
                linked_skus_list.addItem(list_item)
                existing_skus.add(input_sku)
                added_count += 1
                not_found_skus.append(input_sku)
        
        # 入力フィールドをクリア
        sku_input_edit.clear()
        
        # 合計金額を更新
        receipt_total = None
        if total_edit:
            try:
                receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
            except ValueError:
                receipt_total = 0
        self._update_sku_total(linked_skus_list, receipt_total)
        
        # 結果メッセージを表示
        if not_found_skus:
            QMessageBox.warning(
                self, "一部SKUが見つかりませんでした",
                f"{added_count} 件のSKUを追加しました。\n"
                f"以下のSKUは仕入DBに見つかりませんでした（価格不明として追加）:\n{', '.join(not_found_skus)}"
            )
        elif added_count > 0:
            QMessageBox.information(self, "追加完了", f"{added_count} 件のSKUを追加しました。")
        else:
            QMessageBox.information(self, "情報", "追加できるSKUがありませんでした（既に追加済みの可能性があります）。")
    
    def _remove_sku_from_list(self, sku_list: QListWidget, total_edit=None):
        """選択されたSKUを削除"""
        selected_items = sku_list.selectedItems()
        for item in selected_items:
            row = sku_list.row(item)
            sku_list.takeItem(row)
        
        # 合計金額を更新
        receipt_total = None
        if total_edit:
            try:
                receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
            except ValueError:
                receipt_total = 0
        self._update_sku_total(sku_list, receipt_total)
    
    def _edit_sku_price(self, item: QListWidgetItem, sku_list: QListWidget, total_edit, discount_edit):
        """SKU金額を編集（仕入れ個数 × 仕入れ価格の合計金額）"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QSpinBox, QDialogButtonBox
        
        # 現在の金額を取得（仕入れ個数 × 仕入れ価格の合計）
        text = item.text()
        current_total_amount = 0
        if " - ¥" in text:
            try:
                price_str = text.split(" - ¥")[1].replace(",", "").strip()
                current_total_amount = int(price_str)
            except (ValueError, IndexError):
                pass
        
        # SKUを取得
        sku = item.data(Qt.UserRole)
        if not sku:
            if " - " in text:
                sku = text.split(" - ")[0].strip()
            else:
                sku = text.strip()
        
        # 仕入DBから仕入れ個数を取得
        quantity = 1
        if self.product_widget:
            purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
            for record in purchase_records:
                record_sku = record.get('SKU') or record.get('sku', '')
                if record_sku and record_sku.strip() == sku:
                    quantity = record.get('仕入れ個数') or record.get('仕入個数') or record.get('quantity') or record.get('数量', 1)
                    try:
                        quantity = float(quantity) if quantity else 1
                    except (ValueError, TypeError):
                        quantity = 1
                    break
        
        # カスタム金額入力ダイアログ（文字色を確実に表示）
        dialog = QDialog(self)
        dialog.setWindowTitle("金額編集")
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # ラベル（仕入れ個数も表示）
        label_text = f"SKU: {sku}\n仕入れ個数: {int(quantity)}\n新しい合計金額（仕入れ個数 × 仕入れ価格）を入力してください:"
        label = QLabel(label_text)
        label.setStyleSheet("color: #000000;")  # 黒色で確実に表示
        layout.addWidget(label)
        
        # スピンボックス
        spinbox = QSpinBox()
        spinbox.setMinimum(0)
        spinbox.setMaximum(9999999)
        spinbox.setValue(int(current_total_amount))
        spinbox.setStyleSheet("""
            QSpinBox {
                color: #000000;
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                padding: 5px;
                font-size: 12pt;
            }
            QSpinBox:focus {
                border: 2px solid #007bff;
            }
        """)
        layout.addWidget(spinbox)
        
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # ダイアログを表示
        if dialog.exec() == QDialog.Accepted:
            new_total_amount = spinbox.value()
            
            # 仕入れ価格を計算（合計金額 / 仕入れ個数）
            if quantity > 0:
                new_price = new_total_amount / quantity
            else:
                new_price = new_total_amount
            
            # 表示を更新（合計金額と時刻を表示）
            # 既存の表示テキストから時刻情報を取得
            current_text = item.text()
            time_str = "時刻不明"
            if "(" in current_text and ")" in current_text:
                try:
                    time_start = current_text.rfind("(")
                    time_end = current_text.rfind(")")
                    if time_start < time_end:
                        time_str = current_text[time_start+1:time_end]
                except Exception:
                    pass
            
            display_text = f"{sku} - ¥{int(new_total_amount):,} - ({time_str})"
            item.setText(display_text)
            # UserRole + 1に仕入れ価格を保存（仕入DB更新時に使用）
            item.setData(Qt.UserRole + 1, int(new_price))
            
            # 合計と差額を更新
            receipt_total = None
            if total_edit:
                try:
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                except ValueError:
                    receipt_total = 0
            self._update_sku_total(sku_list, receipt_total)
    
    def _update_sku_total(self, sku_list: QListWidget, receipt_total: int = None):
        """SKUリストの合計金額と差額を更新"""
        # 親ウィジェットから合計ラベルを取得
        parent = sku_list.parent()
        if not parent:
            return
        
        # 合計金額を計算（表示テキストから金額を取得：仕入れ個数 × 仕入れ価格の合計）
        total_price = 0
        for i in range(sku_list.count()):
            item = sku_list.item(i)
            if item:
                # 表示テキストから合計金額を抽出
                # 形式: 「SKU - ¥金額 - (時刻)」または「SKU - ¥金額」または「SKU - 価格不明 - (時刻)」
                text = item.text()
                total_amount = 0
                
                if " - ¥" in text:
                    try:
                        # 「 - ¥金額 - (時刻)」または「 - ¥金額」形式から金額を抽出
                        price_part = text.split(" - ¥")[1]
                        # 時刻部分を除去（「 - (時刻)」がある場合）
                        if " - (" in price_part:
                            price_str = price_part.split(" - (")[0].replace(",", "").strip()
                        else:
                            price_str = price_part.replace(",", "").strip()
                        total_amount = int(price_str)
                    except (ValueError, IndexError):
                        total_amount = 0
                elif "¥" in text:
                    # フォールバック: 「¥金額」形式を直接検索
                    try:
                        price_parts = text.split("¥")
                        if len(price_parts) > 1:
                            price_str = price_parts[1].split()[0].replace(",", "").strip()
                            total_amount = int(price_str)
                    except (ValueError, IndexError):
                        total_amount = 0
                
                total_price += total_amount
        
        # レシート合計を取得（引数で指定されていない場合）
        if receipt_total is None:
            # 親ウィジェットから合計入力欄を探す
            total_edit = parent.findChild(QLineEdit)
            if total_edit:
                try:
                    receipt_total = int(total_edit.text()) if total_edit.text().strip() else 0
                except ValueError:
                    receipt_total = 0
            else:
                receipt_total = 0
        
        # 差額を計算
        difference = total_price - receipt_total
        difference_text, difference_color = self._format_price_difference_display(difference)
        
        # 合計ラベルを更新（オブジェクト名で検索）
        total_label = parent.findChild(QLabel, "sku_total_label")
        if total_label:
            total_label.setText(f"合計: ¥{int(total_price):,} ({difference_text})")
            total_label.setStyleSheet(f"font-weight: bold; font-size: 12pt; color: {difference_color};")
        else:
            # オブジェクト名で見つからない場合はレイアウトから探す
            layout = parent.layout()
            if layout:
                for i in range(layout.count()):
                    widget = layout.itemAt(i).widget()
                    if isinstance(widget, QLabel) and widget.text().startswith("合計:"):
                        widget.setText(f"合計: ¥{int(total_price):,} ({difference_text})")
                        widget.setStyleSheet(f"font-weight: bold; font-size: 12pt; color: {difference_color};")
                        break
    
    def confirm_receipt_linkage(self):
        """確定ボタン: レシート管理で紐付けられた画像ファイル名を仕入DBのSKUに設定"""
        if not self._require_bulk_rename_before_post_actions("確定"):
            return
        if not self._require_gcs_upload_before_confirm():
            return
        from time import perf_counter
        if getattr(self, "_confirm_in_progress", False):
            print("[WARN] confirm_receipt_linkage is already running. skip duplicated call.")
            QMessageBox.information(self, "処理中", "確定処理はすでに実行中です。完了までお待ちください。")
            return
        self._confirm_in_progress = True
        if hasattr(self, "confirm_btn") and self.confirm_btn:
            try:
                self.confirm_btn.setEnabled(False)
            except Exception:
                pass
        # 安全優先: まずは従来処理をデフォルトにする。
        # 高速化版は安定確認が取れるまで明示フラグ時のみ有効化。
        use_optimized = False
        try:
            if use_optimized:
                return self._confirm_receipt_linkage_optimized()
        except Exception:
            # 高速化版で問題が起きた場合のみ既存処理へフォールバック
            import traceback
            print(f"[WARN] 高速化版 confirm 処理でエラー。既存処理へフォールバックします。\n{traceback.format_exc()}")

        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        
        # デバッグ: メソッドが呼ばれたことを確認
        print(f"[DEBUG] confirm_receipt_linkage が呼ばれました")
        print(f"[DEBUG] product_widget: {self.product_widget}")
        perf_t0 = perf_counter()
        perf_marks = {}
        print("[PERF] confirm_receipt_linkage start")
        
        # product_widgetが設定されていない場合は警告を表示
        if not hasattr(self, 'product_widget') or not self.product_widget:
            QMessageBox.warning(
                self, "エラー",
                "仕入管理ウィジェットが設定されていません。\n"
                "データベース管理タブを開いてから再度お試しください。"
            )
            return
        
        # レシート一覧から紐付け情報を取得
        updated_count = 0
        warranty_updated_count = 0  # 保証書情報の更新件数
        error_count = 0
        error_messages = []
        
        try:
            # 現在のレシート一覧・保証書一覧に表示されているレコードのみ取得
            all_receipts = self._get_current_receipts_from_tables()
            print(f"[DEBUG] レシート件数（現在の一覧）: {len(all_receipts)}")
            perf_marks["load_current_receipts"] = perf_counter()
            print(f"[PERF] load_current_receipts={perf_marks['load_current_receipts'] - perf_t0:.3f}s")
            
            # 保証書テーブルの行数を取得
            warranty_row_count = 0
            if hasattr(self, 'warranty_table') and self.warranty_table:
                warranty_row_count = self.warranty_table.rowCount()
            
            # 処理ステップ数を計算
            # 進捗バーが100%になった後に重い後処理が残ると体感的に「止まった」ように見えるため、
            # 後処理分（スナップ保存・テーブル更新・仕訳帳UI更新・ルートフラグ更新）も明示的に含める。
            post_steps = 4
            total_steps = len(all_receipts) + warranty_row_count + len(all_receipts) + post_steps
            
            # プログレスダイアログを表示
            progress = QProgressDialog("確定処理中...", "キャンセル", 0, total_steps, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)  # 即座に表示
            progress.setValue(0)
            progress.show()
            QCoreApplication.processEvents()  # UIを更新
            
            current_step = 0
            
            for receipt in all_receipts:
                # キャンセルチェック
                if progress.wasCanceled():
                    QMessageBox.information(self, "確定処理", "確定処理がキャンセルされました。")
                    return
                
                current_step += 1
                progress.setValue(current_step)
                progress.setLabelText(f"確定処理中... (レシート処理: {current_step}/{len(all_receipts)})")
                QCoreApplication.processEvents()  # UIを更新
                
                receipt_id = receipt.get('id')
                
                # 種別判定（OCRテキストから簡易判定）- レシートのみを対象にする
                ocr_text = receipt.get('ocr_text') or ""
                doc_type = "レシート"
                if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                    doc_type = "保証書"
                
                # 保証書はスキップ（レシートのみを処理）
                if doc_type == "保証書":
                    continue
                
                # 画像ファイルパスを取得（original_file_pathを優先、なければfile_path）
                file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
                if not file_path:
                    continue
                
                # ファイルパスが存在するか確認
                image_file = Path(file_path)
                if not image_file.exists():
                    # ファイルが存在しない場合はスキップ（エラーログに記録）
                    error_count += 1
                    error_messages.append(f"レシートID {receipt_id}: 画像ファイルが見つかりません: {file_path}")
                    # デバッグログ
                    try:
                        from pathlib import Path as P
                        log_path = P(__file__).resolve().parents[2] / "desktop_error.log"
                        with open(log_path, "a", encoding="utf-8") as f:
                            from datetime import datetime
                            f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 確定ボタン: ファイルが見つかりません\n")
                            f.write(f"  receipt_id: {receipt_id}\n")
                            f.write(f"  file_path: {file_path}\n")
                            f.write(f"  original_file_path: {receipt.get('original_file_path')}\n")
                            f.write(f"  file_path (DB): {receipt.get('file_path')}\n")
                    except Exception:
                        pass
                    continue
                
                # ファイル名（拡張子なし）を取得（表示用）
                # レシート一覧テーブルと同じ方法で取得（Path(file_path).nameから拡張子を除去）
                image_file_name = image_file.stem
                if not image_file_name:
                    continue
                
                # レシート画像URLを取得（GCSアップロード後のURL）
                receipt_image_url = receipt.get('gcs_url') or receipt.get('image_url') or ''
                
                # 紐付けられたSKUを取得
                linked_skus_text = receipt.get('linked_skus', '') or ''
                linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()] if linked_skus_text else []
                
                print(f"[DEBUG] レシートID {receipt_id}: linked_skus_text={linked_skus_text}, linked_skus={linked_skus}, receipt_image_url={receipt_image_url}")
                
                if not linked_skus:
                    print(f"[DEBUG] レシートID {receipt_id}: SKUが紐付けられていないためスキップ")
                    continue
                
                # 各SKUに対して仕入DBを更新
                for sku in linked_skus:
                    try:
                        # 仕入DBから該当SKUのレコードを取得
                        if not hasattr(self, 'product_widget') or not self.product_widget:
                            continue
                        
                        # まず、purchase_all_recordsを更新（確実に反映）
                        found_in_records = False
                        if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                            for record in self.product_widget.purchase_all_records:
                                record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                if record_sku == sku:
                                    # ファイル名（拡張子なし）を保存（表示用）
                                    # 実際のファイルパスはreceipt_dbから検索できる
                                    record['レシート画像'] = image_file_name
                                    record['レシート画像パス'] = str(image_file.resolve())
                                    # レシート画像URLを保存
                                    if receipt_image_url:
                                        record['レシート画像URL'] = receipt_image_url
                                    found_in_records = True
                                    break
                        
                        # ProductDatabaseから商品を取得して更新（永続化のため）
                        product = self.product_widget.db.get_by_sku(sku)
                        if product:
                            # レシート画像を更新
                            product['receipt_id'] = image_file_name
                            # レシート画像URLを更新
                            if receipt_image_url:
                                product['receipt_image_url'] = receipt_image_url
                            self.product_widget.db.upsert(product)
                        else:
                            # ProductDatabaseに商品がない場合は、最小限の情報で作成
                            try:
                                # purchase_all_recordsから商品情報を取得
                                product_data = None
                                if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                                    for record in self.product_widget.purchase_all_records:
                                        record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                        if record_sku == sku:
                                            product_data = {
                                                'sku': sku,
                                                'receipt_id': image_file_name,
                                                'product_name': record.get('商品名') or record.get('product_name'),
                                                'jan': record.get('JAN') or record.get('jan'),
                                                'asin': record.get('ASIN') or record.get('asin'),
                                                'purchase_price': record.get('仕入れ価格') or record.get('purchase_price'),
                                                'purchase_date': record.get('仕入れ日') or record.get('purchase_date'),
                                            }
                                            # レシート画像URLを追加
                                            if receipt_image_url:
                                                product_data['receipt_image_url'] = receipt_image_url
                                            break
                                
                                if product_data:
                                    self.product_widget.db.upsert(product_data)
                            except Exception as e:
                                import traceback
                                print(f"ProductDatabase作成エラー (SKU={sku}): {e}\n{traceback.format_exc()}")
                        
                        if not found_in_records:
                            updated_count += 1
                        
                        # 仕入管理タブのデータを確認
                        if hasattr(self.product_widget, 'inventory_data') and self.product_widget.inventory_data is not None:
                            import pandas as pd
                            for idx, row in self.product_widget.inventory_data.iterrows():
                                row_sku = str(row.get('SKU') or '').strip()
                                if row_sku == sku:
                                    if 'レシート画像' not in self.product_widget.inventory_data.columns:
                                        self.product_widget.inventory_data['レシート画像'] = ''
                                    self.product_widget.inventory_data.at[idx, 'レシート画像'] = image_file_name
                                    # レシート画像URLを保存
                                    if receipt_image_url:
                                        if 'レシート画像URL' not in self.product_widget.inventory_data.columns:
                                            self.product_widget.inventory_data['レシート画像URL'] = ''
                                        self.product_widget.inventory_data.at[idx, 'レシート画像URL'] = receipt_image_url
                                    if not found_in_records:
                                        updated_count += 1
                                    break
                        
                        # filtered_dataも更新
                        if hasattr(self.product_widget, 'filtered_data') and self.product_widget.filtered_data is not None:
                            for idx, row in self.product_widget.filtered_data.iterrows():
                                row_sku = str(row.get('SKU') or '').strip()
                                if row_sku == sku:
                                    if 'レシート画像' not in self.product_widget.filtered_data.columns:
                                        self.product_widget.filtered_data['レシート画像'] = ''
                                    self.product_widget.filtered_data.at[idx, 'レシート画像'] = image_file_name
                                    # レシート画像URLを保存
                                    if receipt_image_url:
                                        if 'レシート画像URL' not in self.product_widget.filtered_data.columns:
                                            self.product_widget.filtered_data['レシート画像URL'] = ''
                                        self.product_widget.filtered_data.at[idx, 'レシート画像URL'] = receipt_image_url
                                    break
                        
                        if found_in_records:
                            updated_count += 1
                    except Exception as e:
                        error_count += 1
                        error_messages.append(f"SKU {sku}: {str(e)}")
                        import traceback
                        print(f"確定処理エラー (SKU={sku}): {e}\n{traceback.format_exc()}")
            perf_marks["receipt_sku_reflect"] = perf_counter()
            print(f"[PERF] receipt_sku_reflect={perf_marks['receipt_sku_reflect'] - perf_marks.get('load_current_receipts', perf_t0):.3f}s")
            
            # 保証書一覧から情報を取得して仕入DBに反映
            if hasattr(self, 'warranty_table') and self.warranty_table.rowCount() > 0:
                warranty_updated_count = 0
                warranty_total = self.warranty_table.rowCount()
                for warranty_row in range(warranty_total):
                    # キャンセルチェック
                    if progress.wasCanceled():
                        QMessageBox.information(self, "確定処理", "確定処理がキャンセルされました。")
                        return
                    
                    current_step += 1
                    progress.setValue(current_step)
                    progress.setLabelText(f"確定処理中... (保証書処理: {warranty_row + 1}/{warranty_total})")
                    QCoreApplication.processEvents()  # UIを更新
                    try:
                        # まずテーブル上の代表SKUを取得（後方互換用）
                        sku_item = self.warranty_table.item(warranty_row, 7)  # SKU列
                        base_sku = sku_item.text().strip() if sku_item else ""
                        
                        # receipt_idから保証書情報を取得
                        id_item = self.warranty_table.item(warranty_row, 0)  # ID列
                        if not id_item:
                            continue
                        try:
                            receipt_id = int(id_item.text())
                        except ValueError:
                            continue
                        
                        # receipt_idからレシートDBから情報を取得
                        receipt_info = self.receipt_db.get_receipt(receipt_id)
                        warranty_image_name = ""
                        linked_skus_from_receipt: List[str] = []
                        if receipt_info:
                            # ファイルパスを取得（original_file_pathを優先、なければfile_path）
                            file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path', '')
                            if file_path:
                                from pathlib import Path
                                file_path_obj = Path(file_path)
                                # ファイルの有無にかかわらずファイル名（拡張子なし）を取得
                                warranty_image_name = file_path_obj.stem
                            
                            # レシート側に保存されている linked_skus を優先して使用
                            linked_skus_text = receipt_info.get('linked_skus', '') or ''
                            if linked_skus_text:
                                linked_skus_from_receipt = [
                                    s.strip() for s in linked_skus_text.split(',') if s.strip()
                                ]
                        
                        # 対象SKUリストを決定
                        target_skus: List[str] = []
                        if linked_skus_from_receipt:
                            target_skus = linked_skus_from_receipt
                        elif base_sku:
                            # linked_skus が無い古いデータ用に、テーブル上のSKUを1件だけ処理
                            target_skus = [base_sku]
                        else:
                            # 対象SKUが無い場合はスキップ
                            continue
                        
                        # 保証期間(日)を取得
                        warranty_days_item = self.warranty_table.item(warranty_row, 9)  # 保証期間(日)列
                        warranty_days = None
                        if warranty_days_item:
                            warranty_days_text = warranty_days_item.text().strip()
                            if warranty_days_text:
                                try:
                                    warranty_days = int(warranty_days_text)
                                except ValueError:
                                    pass
                        
                        # 保証最終日を取得
                        warranty_until = None
                        warranty_until_widget = self.warranty_table.cellWidget(warranty_row, 10)  # 保証最終日列（QDateEdit）
                        if warranty_until_widget:
                            from PySide6.QtWidgets import QDateEdit
                            if isinstance(warranty_until_widget, QDateEdit):
                                qdate = warranty_until_widget.date()
                                if qdate.isValid():
                                    warranty_until = qdate.toString("yyyy-MM-dd")
                        
                        # 仕入DBから該当SKU群のレコードを取得して更新
                        if not hasattr(self, 'product_widget') or not self.product_widget:
                            continue
                        
                        for sku in target_skus:
                            # purchase_all_recordsを更新
                            found_in_records = False
                            if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                                for record in self.product_widget.purchase_all_records:
                                    record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                    if record_sku == sku:
                                        # 保証書画像を更新
                                        if warranty_image_name:
                                            record['保証書画像'] = warranty_image_name
                                        # 保証期間を更新
                                        if warranty_days is not None:
                                            record['保証期間'] = warranty_days
                                        # 保証最終日を更新
                                        if warranty_until:
                                            record['保証最終日'] = warranty_until
                                        found_in_records = True
                                        break
                            
                            # ProductDatabaseから商品を取得して更新（永続化のため）
                            product = self.product_widget.db.get_by_sku(sku)
                            if product:
                                # 保証期間を更新
                                if warranty_days is not None:
                                    product['warranty_period_days'] = warranty_days
                                
                                # 保証最終日を更新
                                if warranty_until:
                                    product['warranty_until'] = warranty_until
                                
                                self.product_widget.db.upsert(product)
                            else:
                                # ProductDatabaseに商品がない場合は、最小限の情報で作成
                                try:
                                    product_data = None
                                    if hasattr(self.product_widget, 'purchase_all_records') and self.product_widget.purchase_all_records:
                                        for record in self.product_widget.purchase_all_records:
                                            record_sku = str(record.get('SKU') or record.get('sku') or '').strip()
                                            if record_sku == sku:
                                                product_data = {
                                                    'sku': sku,
                                                    'product_name': record.get('商品名') or record.get('product_name'),
                                                    'jan': record.get('JAN') or record.get('jan'),
                                                    'asin': record.get('ASIN') or record.get('asin'),
                                                    'purchase_price': record.get('仕入れ価格') or record.get('purchase_price'),
                                                    'purchase_date': record.get('仕入れ日') or record.get('purchase_date'),
                                                }
                                                # 保証書情報を追加
                                                if warranty_image_name:
                                                    product_data['warranty_image'] = warranty_image_name
                                                if warranty_days is not None:
                                                    product_data['warranty_period_days'] = warranty_days
                                                if warranty_until:
                                                    product_data['warranty_until'] = warranty_until
                                                break
                                    
                                    if product_data:
                                        self.product_widget.db.upsert(product_data)
                                except Exception as e:
                                    import traceback
                                    print(f"ProductDatabase作成エラー (SKU={sku}): {e}\n{traceback.format_exc()}")
                            
                            # 仕入管理タブのデータを確認
                            if hasattr(self.product_widget, 'inventory_data') and self.product_widget.inventory_data is not None:
                                import pandas as pd
                                for idx, row in self.product_widget.inventory_data.iterrows():
                                    row_sku = str(row.get('SKU') or '').strip()
                                    if row_sku == sku:
                                        # 保証書画像を更新
                                        if warranty_image_name:
                                            if '保証書画像' not in self.product_widget.inventory_data.columns:
                                                self.product_widget.inventory_data['保証書画像'] = ''
                                            self.product_widget.inventory_data.at[idx, '保証書画像'] = warranty_image_name
                                        # 保証期間を更新
                                        if warranty_days is not None:
                                            if '保証期間' not in self.product_widget.inventory_data.columns:
                                                self.product_widget.inventory_data['保証期間'] = ''
                                            self.product_widget.inventory_data.at[idx, '保証期間'] = warranty_days
                                        # 保証最終日を更新
                                        if warranty_until:
                                            if '保証最終日' not in self.product_widget.inventory_data.columns:
                                                self.product_widget.inventory_data['保証最終日'] = ''
                                            self.product_widget.inventory_data.at[idx, '保証最終日'] = warranty_until
                                        if not found_in_records:
                                            warranty_updated_count += 1
                                        break
                            
                            # filtered_dataも更新
                            if hasattr(self.product_widget, 'filtered_data') and self.product_widget.filtered_data is not None:
                                for idx, row in self.product_widget.filtered_data.iterrows():
                                    row_sku = str(row.get('SKU') or '').strip()
                                    if row_sku == sku:
                                        # 保証書画像を更新
                                        if warranty_image_name:
                                            if '保証書画像' not in self.product_widget.filtered_data.columns:
                                                self.product_widget.filtered_data['保証書画像'] = ''
                                            self.product_widget.filtered_data.at[idx, '保証書画像'] = warranty_image_name
                                        # 保証期間を更新
                                        if warranty_days is not None:
                                            if '保証期間' not in self.product_widget.filtered_data.columns:
                                                self.product_widget.filtered_data['保証期間'] = ''
                                            self.product_widget.filtered_data.at[idx, '保証期間'] = warranty_days
                                        # 保証最終日を更新
                                        if warranty_until:
                                            if '保証最終日' not in self.product_widget.filtered_data.columns:
                                                self.product_widget.filtered_data['保証最終日'] = ''
                                            self.product_widget.filtered_data.at[idx, '保証最終日'] = warranty_until
                                        break
                            
                            # 件数カウント（SKUごとに1件）
                            warranty_updated_count += 1
                    except Exception as e:
                        error_count += 1
                        error_messages.append(f"保証書処理エラー (SKU={sku if 'sku' in locals() else '不明'}): {str(e)}")
                        import traceback
                        print(f"保証書確定処理エラー: {e}\n{traceback.format_exc()}")
                
                updated_count += warranty_updated_count
            perf_marks["warranty_reflect"] = perf_counter()
            print(f"[PERF] warranty_reflect={perf_marks['warranty_reflect'] - perf_marks.get('receipt_sku_reflect', perf_t0):.3f}s")
            
            # 仕入管理タブのテーブル表示を更新
            if updated_count > 0 and hasattr(self, 'product_widget') and self.product_widget:
                # スナップショットを保存（アプリ再起動後も保持されるように）
                if hasattr(self.product_widget, 'save_purchase_snapshot'):
                    current_step += 1
                    progress.setValue(current_step)
                    progress.setLabelText("確定処理中... (後処理: スナップショット保存)")
                    QCoreApplication.processEvents()
                    try:
                        self.product_widget.save_purchase_snapshot()
                    except Exception as e:
                        import traceback
                        print(f"スナップショット保存エラー: {e}\n{traceback.format_exc()}")
                    finally:
                        perf_marks["save_purchase_snapshot"] = perf_counter()
                        print(f"[PERF] save_purchase_snapshot={perf_marks['save_purchase_snapshot'] - perf_marks.get('warranty_reflect', perf_t0):.3f}s")
                
                if hasattr(self.product_widget, 'update_table'):
                    current_step += 1
                    progress.setValue(current_step)
                    progress.setLabelText("確定処理中... (後処理: 仕入テーブル更新)")
                    QCoreApplication.processEvents()
                    try:
                        self.product_widget.sync_purchase_master_from_records()
                    except Exception:
                        pass
                    pw_ref = self.product_widget
                    QTimer.singleShot(0, pw_ref.refresh_purchase_table_if_built)
                perf_marks["purchase_refresh_deferred"] = perf_counter()
                print(f"[PERF] purchase_refresh_deferred={perf_marks['purchase_refresh_deferred'] - perf_marks.get('save_purchase_snapshot', perf_marks.get('warranty_reflect', perf_t0)):.3f}s")
            else:
                # updated_count == 0 の場合も進捗は実際の処理段階に合わせて進める
                current_step += 1
                progress.setValue(current_step)
                progress.setLabelText("確定処理中... (後処理: スナップショット保存スキップ)")
                QCoreApplication.processEvents()
                perf_marks["purchase_refresh_skipped"] = perf_counter()
                print(f"[PERF] purchase_refresh_skipped={perf_marks['purchase_refresh_skipped'] - perf_marks.get('warranty_reflect', perf_t0):.3f}s")
                current_step += 1
                progress.setValue(current_step)
                progress.setLabelText("確定処理中... (後処理: 仕入テーブル更新スキップ)")
                QCoreApplication.processEvents()
            
            # 仕訳帳への自動登録処理
            journal_count = 0
            try:
                from desktop.database.journal_db import JournalDatabase
                from desktop.database.account_title_db import AccountTitleDatabase
                from datetime import datetime
                import re
                
                journal_db = JournalDatabase()
                account_title_db = AccountTitleDatabase()
                
                # デフォルトの借方勘定科目（仕入）
                default_debit = "仕入"
                
                # デフォルトの貸方勘定科目を取得
                default_credit_account = account_title_db.get_default_credit_account()
                default_credit = "現金"  # フォールバック
                if default_credit_account:
                    name = default_credit_account.get("name", "")
                    card_name = default_credit_account.get("card_name", "")
                    last_four = default_credit_account.get("last_four_digits", "")
                    if card_name and last_four:
                        default_credit = f"{name} ({card_name} ****{last_four})"
                    elif card_name:
                        default_credit = f"{name} ({card_name})"
                    else:
                        default_credit = name
                
                # レシート一覧から仕訳帳に登録
                skipped_reasons = {
                    "保証書": 0,
                    "科目が仕入でない": 0,
                    "日付なし": 0,
                    "金額0": 0,
                    "既に登録済み": 0
                }
                # 高速化: 同じ日付・同じ店舗コードは毎回DB参照しない
                journal_entries_cache = {}
                store_name_cache = {}
                
                journal_receipt_count = 0
                for receipt in all_receipts:
                    one_journal_t0 = perf_counter()
                    # キャンセルチェック
                    if progress.wasCanceled():
                        QMessageBox.information(self, "確定処理", "確定処理がキャンセルされました。")
                        return
                    
                    current_step += 1
                    journal_receipt_count += 1
                    progress.setValue(current_step)
                    progress.setLabelText(f"確定処理中... (仕訳帳登録: {journal_receipt_count}/{len(all_receipts)})")
                    QCoreApplication.processEvents()  # UIを更新
                    receipt_id = receipt.get('id')
                    
                    # 種別判定（レシートのみを対象）
                    ocr_text = receipt.get('ocr_text') or ""
                    doc_type = "レシート"
                    if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                        doc_type = "保証書"
                    
                    if doc_type == "保証書":
                        skipped_reasons["保証書"] += 1
                        continue
                    
                    # 科目を取得（空欄の場合は「仕入」として扱う）
                    account_title = (receipt.get('account_title') or '').strip()
                    if not account_title:
                        account_title = default_debit  # 空欄の場合は「仕入」として扱う
                    
                    # 日付＋時刻を取得
                    raw_purchase_date = receipt.get('purchase_date', '') or ''
                    if not raw_purchase_date:
                        skipped_reasons["日付なし"] += 1
                        print(f"[DEBUG] 仕訳帳スキップ (receipt_id={receipt_id}): 日付なし")
                        continue
                    # 文字列表現を正規化（例: "2025-02-17T10:30" -> "2025-02-17 10:30"）
                    purchase_datetime = raw_purchase_date.replace('T', ' ').strip()
                    # 検索用に「日付のみ」も保持（重複チェックは日付単位で行う）
                    purchase_date_only = purchase_datetime.split(' ')[0]
                    
                    # 合計金額を取得
                    total_amount = receipt.get('total_amount', 0) or 0
                    if not total_amount or total_amount == 0:
                        skipped_reasons["金額0"] += 1
                        print(f"[DEBUG] 仕訳帳スキップ (receipt_id={receipt_id}): 金額が0 (total_amount={total_amount})")
                        continue
                    
                    # 店舗名を取得（店舗コードから店舗マスタを参照）
                    store_code = receipt.get('store_code', '') or ''
                    store_name = ''
                    
                    if store_code:
                        # 店舗マスタから店舗名を取得
                        if store_code in store_name_cache:
                            store_name = store_name_cache.get(store_code, '')
                        else:
                            try:
                                store = self.store_db.get_store_by_code(store_code)
                                if store:
                                    store_name = store.get('store_name', '') or ''
                                store_name_cache[store_code] = store_name
                            except Exception as e:
                                print(f"[DEBUG] 店舗マスタ取得エラー (store_code={store_code}): {e}")
                                store_name_cache[store_code] = ''
                    
                    # 店舗マスタから取得できない場合は、既存の方法で取得（フォールバック）
                    if not store_name:
                        store_name = receipt.get('store_name_raw', '') or receipt.get('store_name', '') or ''
                        # 店舗コード（ss-53等）を除去
                        if store_name:
                            # パターン: "店舗名 (ss-53)" や "店舗名 ss-53" を除去
                            store_name = re.sub(r'\s*\([^)]*\)', '', store_name)  # 括弧内を除去
                            store_name = re.sub(r'\s+ss-\d+', '', store_name, flags=re.IGNORECASE)  # ss-53等を除去
                            store_name = store_name.strip()
                    
                    # 登録番号を取得
                    registration_number = receipt.get('registration_number', '') or ''
                    
                    # 画像URLを取得
                    image_url = receipt.get('gcs_url') or receipt.get('image_url') or ''

                    # 既に登録されているかチェック
                    #   1. 同じ日付の範囲で取得
                    #   2. まず画像URL一致を優先
                    #   3. 見つからなければ「日付（同一日）＋金額＋摘要（店舗名）」一致で重複判定
                    if purchase_date_only in journal_entries_cache:
                        existing_entries = journal_entries_cache[purchase_date_only]
                    else:
                        existing_entries = journal_db.list_by_date(
                            purchase_date_only,
                            f"{purchase_date_only} 23:59:59"
                        )
                        journal_entries_cache[purchase_date_only] = existing_entries
                    existing_entry = None

                    # 1) 画像URLで既存エントリを検索
                    if image_url:
                        for e in existing_entries:
                            if e.get('image_url') == image_url:
                                existing_entry = e
                                break

                    # 2) 画像URLが一致しない場合は「日付＋金額＋摘要（店舗名）」で重複判定
                    if existing_entry is None:
                        for e in existing_entries:
                            if (
                                e.get('amount') == total_amount and
                                (e.get('description') or '') == store_name
                            ):
                                existing_entry = e
                                break

                    # 仕訳帳エントリのデータ（借方勘定科目はレシートの科目を使用：仕入・旅費交通費・消耗品費など）
                    journal_entry = {
                        # 取引日付には「日付＋時刻」を保存
                        "transaction_date": purchase_datetime,
                        "debit_account": account_title,
                        "amount": total_amount,
                        "credit_account": default_credit,
                        "description": store_name,
                        "invoice_number": registration_number,
                        "tax_category": "10％",
                        "image_url": image_url
                    }
                    
                    try:
                        if existing_entry:
                            # 既に登録済みの場合は更新（変更がある場合は修正）
                            existing_id = existing_entry.get('id')
                            if existing_id:
                                # 変更があるかチェック
                                has_changes = (
                                    existing_entry.get('transaction_date') != purchase_datetime or
                                    existing_entry.get('debit_account') != account_title or
                                    existing_entry.get('amount') != total_amount or
                                    existing_entry.get('credit_account') != default_credit or
                                    existing_entry.get('description') != store_name or
                                    existing_entry.get('invoice_number') != registration_number or
                                    existing_entry.get('tax_category') != "10％" or
                                    existing_entry.get('image_url') != image_url
                                )
                                
                                if has_changes:
                                    journal_db.update(existing_id, journal_entry)
                                    journal_count += 1
                                    print(f"[DEBUG] 仕訳帳更新成功 (receipt_id={receipt_id}, journal_id={existing_id}): date={purchase_datetime}, amount={total_amount}, store={store_name}")
                                else:
                                    print(f"[DEBUG] 仕訳帳スキップ (receipt_id={receipt_id}): 変更なし (journal_id={existing_id})")
                        else:
                            # 新規登録
                            new_id = journal_db.insert(journal_entry)
                            journal_count += 1
                            # キャッシュにも追加して、同一実行内の重複チェック精度と速度を維持
                            cache_entry = dict(journal_entry)
                            cache_entry["id"] = new_id
                            existing_entries.append(cache_entry)
                            print(f"[DEBUG] 仕訳帳登録成功 (receipt_id={receipt_id}): date={purchase_datetime}, amount={total_amount}, store={store_name}")
                    except Exception as e:
                        print(f"[DEBUG] 仕訳帳登録/更新エラー (receipt_id={receipt_id}): {e}")
                        error_count += 1
                        error_messages.append(f"仕訳帳登録/更新エラー (receipt_id={receipt_id}): {str(e)}")
                    finally:
                        one_journal_dt = perf_counter() - one_journal_t0
                        print(f"[PERF] journal_per_receipt receipt_id={receipt_id} elapsed={one_journal_dt:.3f}s")
                
                # スキップ理由をログ出力
                print(f"[DEBUG] 仕訳帳登録スキップ理由: {skipped_reasons}")
                
                # 仕訳帳タブを更新（もし開いていれば）
                current_step += 1
                progress.setValue(current_step)
                progress.setLabelText("確定処理中... (後処理: 仕訳帳タブ更新)")
                QCoreApplication.processEvents()
                if hasattr(self, 'evidence_widget'):
                    try:
                        if hasattr(self.evidence_widget, 'journal_entry_widget'):
                            journal_widget = self.evidence_widget.journal_entry_widget
                            # フリーズ回避最優先:
                            # 確定処理中には仕訳帳タブの全件再描画(load_entries)を実行しない。
                            # 次回タブ表示時に遅延ロードさせる。
                            setattr(journal_widget, "_initial_data_loaded", False)
                    except Exception:
                        pass
                perf_marks["journal_phase_total"] = perf_counter()
                print(f"[PERF] journal_phase_total={perf_marks['journal_phase_total'] - perf_marks.get('purchase_refresh_deferred', perf_marks.get('purchase_refresh_skipped', perf_t0)):.3f}s")
            except Exception as e:
                import traceback
                print(f"[DEBUG] 仕訳帳自動登録処理エラー: {e}\n{traceback.format_exc()}")
                # 仕訳帳処理で例外が出ても、進捗段階は揃える
                if current_step < total_steps - 1:
                    current_step += 1
                    progress.setValue(current_step)
                    progress.setLabelText("確定処理中... (後処理: 仕訳帳タブ更新スキップ)")
                    QCoreApplication.processEvents()
                perf_marks["journal_phase_total"] = perf_counter()
            
            # 結果を表示
            receipt_count = updated_count - warranty_updated_count
            warranty_count = warranty_updated_count
            
            print(f"[DEBUG] 確定処理完了: receipt_count={receipt_count}, warranty_count={warranty_count}, journal_count={journal_count}, error_count={error_count}")
            
            # プログレスダイアログを閉じる
            progress.setValue(total_steps)
            progress.close()

            # ルート証憑フラグ（レシート確定完了）— progress 終了後に実行
            try:
                base_folder = getattr(self, "current_folder", None) or getattr(self, "default_folder", None)
                route_id = mark_route_evidence_completed(
                    folder_path=base_folder,
                    receipts=all_receipts,
                )
                if route_id:
                    print(f"[DEBUG] ルート証憑フラグを更新: route_id={route_id}")
                else:
                    print("[DEBUG] ルート証憑フラグ: 対応するルートサマリーが見つかりませんでした")
            except Exception as e:
                print(f"証憑フラグ更新エラー: {e}")

            if receipt_count == 0 and warranty_count == 0 and error_count == 0:
                # 処理対象がなかった場合
                QMessageBox.information(
                    self, "確定",
                    "確定するレコードがありませんでした。\n"
                    "レシート一覧にSKUが紐付けられているレコードがあるか確認してください。"
                )
            elif error_count == 0:
                message = f"{receipt_count} 件のSKUにレシート画像を設定しました。"
                if warranty_count > 0:
                    message += f"\n{warranty_count} 件のSKUに保証書情報（保証書画像・保証期間・保証最終日）を設定しました。"
                if journal_count > 0:
                    message += f"\n{journal_count} 件のレシートを仕訳帳に登録しました。"
                QMessageBox.information(
                    self, "確定完了",
                    message
                )
            else:
                message = f"{receipt_count} 件のSKUにレシート画像を設定しました。"
                if warranty_count > 0:
                    message += f"\n{warranty_count} 件のSKUに保証書情報（保証書画像・保証期間・保証最終日）を設定しました。"
                if journal_count > 0:
                    message += f"\n{journal_count} 件のレシートを仕訳帳に登録しました。"
                message += f"\n\nエラー: {error_count} 件\n" + "\n".join(error_messages[:5])
                QMessageBox.warning(
                    self, "確定完了（一部エラー）",
                    message
                )

            # ルート証憑フラグ更新は予約のみ（progressを再操作しない）
            # ※ close済みのprogressにsetValue/setLabelTextするとダイアログが再表示されることがある。
            perf_marks["route_flag_deferred"] = perf_counter()
            print(f"[PERF] route_flag_deferred={perf_marks['route_flag_deferred'] - perf_marks.get('journal_phase_total', perf_t0):.3f}s")
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, "エラー",
                f"確定処理中にエラーが発生しました:\n{str(e)}\n\n{traceback.format_exc()}"
            )
        finally:
            try:
                if 'progress' in locals() and progress is not None:
                    progress.close()
                    progress.deleteLater()
            except Exception:
                pass
            perf_t_end = perf_counter()
            print(f"[PERF] confirm_receipt_linkage total={perf_t_end - perf_t0:.3f}s")
            self._confirm_in_progress = False
            self._sync_post_rename_action_buttons()

    def _confirm_receipt_linkage_optimized(self):
        """確定処理の高速化版（処理対象の事前集約・検索マップ化で待ち時間を削減）"""
        from pathlib import Path
        from time import perf_counter
        from PySide6.QtWidgets import QMessageBox
        import re
        t0 = perf_counter()
        checkpoints = {}

        if not hasattr(self, 'product_widget') or not self.product_widget:
            QMessageBox.warning(
                self, "エラー",
                "仕入管理ウィジェットが設定されていません。\n"
                "データベース管理タブを開いてから再度お試しください。"
            )
            return

        updated_count = 0
        warranty_updated_count = 0
        journal_count = 0
        error_count = 0
        error_messages = []

        all_receipts = self._get_current_receipts_from_tables()
        warranty_row_count = self.warranty_table.rowCount() if hasattr(self, 'warranty_table') and self.warranty_table else 0
        total_steps = max(1, len(all_receipts) + warranty_row_count + len(all_receipts))

        progress = QProgressDialog("確定処理中...", "キャンセル", 0, total_steps, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QCoreApplication.processEvents()
        current_step = 0

        def tick(label: str, force: bool = False):
            nonlocal current_step
            current_step += 1
            if force or (current_step % 20 == 0) or current_step >= total_steps:
                progress.setValue(min(current_step, total_steps))
                progress.setLabelText(label)
                QCoreApplication.processEvents()
            if progress.wasCanceled():
                QMessageBox.information(self, "確定処理", "確定処理がキャンセルされました。")
                raise RuntimeError("cancelled")

        # ---- 1) SKU単位の更新内容を先に集約 ----
        receipt_updates: dict[str, dict] = {}
        for idx, receipt in enumerate(all_receipts, 1):
            tick(f"確定処理中... (レシート集約: {idx}/{len(all_receipts)})")

            ocr_text = receipt.get('ocr_text') or ""
            if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                continue

            file_path = receipt.get('original_file_path') or receipt.get('file_path', '')
            if not file_path:
                continue
            image_file = Path(file_path)
            if not image_file.exists():
                error_count += 1
                error_messages.append(f"レシートID {receipt.get('id')}: 画像ファイルが見つかりません: {file_path}")
                continue

            image_file_name = image_file.stem
            if not image_file_name:
                continue
            receipt_image_url = receipt.get('gcs_url') or receipt.get('image_url') or ''
            linked_skus_text = receipt.get('linked_skus', '') or ''
            linked_skus = [s.strip() for s in linked_skus_text.split(',') if s.strip()]
            for sku in linked_skus:
                receipt_updates[sku] = {
                    "receipt_id": image_file_name,
                    "receipt_image_path": str(image_file.resolve()),
                    "receipt_image_url": receipt_image_url,
                }
        checkpoints["receipt_collect"] = perf_counter()

        warranty_updates: dict[str, dict] = {}
        if hasattr(self, 'warranty_table') and self.warranty_table and self.warranty_table.rowCount() > 0:
            for warranty_row in range(self.warranty_table.rowCount()):
                tick(f"確定処理中... (保証書集約: {warranty_row + 1}/{self.warranty_table.rowCount()})")
                try:
                    id_item = self.warranty_table.item(warranty_row, 0)
                    if not id_item:
                        continue
                    receipt_id = int(id_item.text())
                    receipt_info = self.receipt_db.get_receipt(receipt_id)
                    if not receipt_info:
                        continue

                    file_path = receipt_info.get('original_file_path') or receipt_info.get('file_path', '')
                    warranty_image_name = Path(file_path).stem if file_path else ""

                    linked_skus_text = receipt_info.get('linked_skus', '') or ''
                    target_skus = [s.strip() for s in linked_skus_text.split(',') if s.strip()]
                    if not target_skus:
                        sku_item = self.warranty_table.item(warranty_row, 7)
                        if sku_item and sku_item.text().strip():
                            target_skus = [sku_item.text().strip()]
                    if not target_skus:
                        continue

                    warranty_days = None
                    warranty_days_item = self.warranty_table.item(warranty_row, 9)
                    if warranty_days_item and warranty_days_item.text().strip():
                        try:
                            warranty_days = int(warranty_days_item.text().strip())
                        except ValueError:
                            warranty_days = None

                    warranty_until = None
                    warranty_until_widget = self.warranty_table.cellWidget(warranty_row, 10)
                    if isinstance(warranty_until_widget, QDateEdit):
                        qdate = warranty_until_widget.date()
                        if qdate.isValid():
                            warranty_until = qdate.toString("yyyy-MM-dd")

                    for sku in target_skus:
                        warranty_updates[sku] = {
                            "warranty_image": warranty_image_name,
                            "warranty_period_days": warranty_days,
                            "warranty_until": warranty_until,
                        }
                except Exception as e:
                    error_count += 1
                    error_messages.append(f"保証書処理エラー: {str(e)}")
        checkpoints["warranty_collect"] = perf_counter()

        # ---- 2) メモリ上データをマップ更新（O(n)） ----
        target_skus_all = set(receipt_updates.keys()) | set(warranty_updates.keys())
        pw = self.product_widget

        purchase_map = {}
        for record in (pw.purchase_all_records or []):
            sku = str(record.get('SKU') or record.get('sku') or '').strip()
            if sku:
                purchase_map[sku] = record

        patches_by_sku: Dict[str, Dict[str, Any]] = {}
        for sku in target_skus_all:
            patch: Dict[str, Any] = {}
            ru = receipt_updates.get(sku)
            wu = warranty_updates.get(sku)
            if ru:
                patch['レシート画像'] = ru.get("receipt_id", "")
                if ru.get("receipt_image_path"):
                    patch['レシート画像パス'] = ru["receipt_image_path"]
                if ru.get("receipt_image_url"):
                    patch['レシート画像URL'] = ru["receipt_image_url"]
            if wu:
                if wu.get("warranty_image"):
                    patch['保証書画像'] = wu["warranty_image"]
                if wu.get("warranty_period_days") is not None:
                    patch['保証期間'] = wu["warranty_period_days"]
                if wu.get("warranty_until"):
                    patch['保証最終日'] = wu["warranty_until"]
            if patch:
                patches_by_sku[sku] = patch

        updated_count = pw.patch_purchase_records_by_sku_map(patches_by_sku)
        warranty_updated_count = sum(
            1 for sku in target_skus_all if sku in warranty_updates
        )

        # DataFrame更新（SKU -> indexの逆引き）
        def build_df_index_map(df):
            idx_map = {}
            if df is None or 'SKU' not in df.columns:
                return idx_map
            for i, sku_val in df['SKU'].items():
                sku = str(sku_val or '').strip()
                if sku:
                    idx_map[sku] = i
            return idx_map

        inv_df = pw.inventory_data if hasattr(pw, 'inventory_data') else None
        fil_df = pw.filtered_data if hasattr(pw, 'filtered_data') else None
        inv_idx_map = build_df_index_map(inv_df)
        fil_idx_map = build_df_index_map(fil_df)

        for sku in target_skus_all:
            ru = receipt_updates.get(sku)
            wu = warranty_updates.get(sku)
            if inv_df is not None and sku in inv_idx_map:
                i = inv_idx_map[sku]
                if ru:
                    if 'レシート画像' not in inv_df.columns:
                        inv_df['レシート画像'] = ''
                    inv_df.at[i, 'レシート画像'] = ru.get("receipt_id", "")
                    if ru.get("receipt_image_path"):
                        if 'レシート画像パス' not in inv_df.columns:
                            inv_df['レシート画像パス'] = ''
                        inv_df.at[i, 'レシート画像パス'] = ru["receipt_image_path"]
                    if ru.get("receipt_image_url"):
                        if 'レシート画像URL' not in inv_df.columns:
                            inv_df['レシート画像URL'] = ''
                        inv_df.at[i, 'レシート画像URL'] = ru["receipt_image_url"]
                if wu:
                    if wu.get("warranty_image"):
                        if '保証書画像' not in inv_df.columns:
                            inv_df['保証書画像'] = ''
                        inv_df.at[i, '保証書画像'] = wu["warranty_image"]
                    if wu.get("warranty_period_days") is not None:
                        if '保証期間' not in inv_df.columns:
                            inv_df['保証期間'] = ''
                        inv_df.at[i, '保証期間'] = wu["warranty_period_days"]
                    if wu.get("warranty_until"):
                        if '保証最終日' not in inv_df.columns:
                            inv_df['保証最終日'] = ''
                        inv_df.at[i, '保証最終日'] = wu["warranty_until"]

            if fil_df is not None and sku in fil_idx_map:
                i = fil_idx_map[sku]
                if ru:
                    if 'レシート画像' not in fil_df.columns:
                        fil_df['レシート画像'] = ''
                    fil_df.at[i, 'レシート画像'] = ru.get("receipt_id", "")
                    if ru.get("receipt_image_path"):
                        if 'レシート画像パス' not in fil_df.columns:
                            fil_df['レシート画像パス'] = ''
                        fil_df.at[i, 'レシート画像パス'] = ru["receipt_image_path"]
                    if ru.get("receipt_image_url"):
                        if 'レシート画像URL' not in fil_df.columns:
                            fil_df['レシート画像URL'] = ''
                        fil_df.at[i, 'レシート画像URL'] = ru["receipt_image_url"]
                if wu:
                    if wu.get("warranty_image"):
                        if '保証書画像' not in fil_df.columns:
                            fil_df['保証書画像'] = ''
                        fil_df.at[i, '保証書画像'] = wu["warranty_image"]
                    if wu.get("warranty_period_days") is not None:
                        if '保証期間' not in fil_df.columns:
                            fil_df['保証期間'] = ''
                        fil_df.at[i, '保証期間'] = wu["warranty_period_days"]
                    if wu.get("warranty_until"):
                        if '保証最終日' not in fil_df.columns:
                            fil_df['保証最終日'] = ''
                        fil_df.at[i, '保証最終日'] = wu["warranty_until"]
        checkpoints["memory_update"] = perf_counter()

        # ---- 3) ProductDB更新（SKUごとに1回） ----
        for i, sku in enumerate(target_skus_all, 1):
            tick(f"確定処理中... (仕入DB更新: {i}/{len(target_skus_all)})")
            try:
                product = pw.db.get_by_sku(sku) or {"sku": sku}
                ru = receipt_updates.get(sku)
                wu = warranty_updates.get(sku)
                if ru:
                    product["receipt_id"] = ru.get("receipt_id", "")
                    if ru.get("receipt_image_url"):
                        product["receipt_image_url"] = ru["receipt_image_url"]
                if wu:
                    if wu.get("warranty_period_days") is not None:
                        product["warranty_period_days"] = wu["warranty_period_days"]
                    if wu.get("warranty_until"):
                        product["warranty_until"] = wu["warranty_until"]
                pw.db.upsert(product)
            except Exception as e:
                error_count += 1
                error_messages.append(f"SKU {sku}: {str(e)}")
        checkpoints["product_db_update"] = perf_counter()

        # ---- 4) 仕訳帳登録（同一日検索をキャッシュ化）----
        from desktop.database.journal_db import JournalDatabase
        from desktop.database.account_title_db import AccountTitleDatabase
        journal_db = JournalDatabase()
        account_title_db = AccountTitleDatabase()
        default_debit = "仕入"
        default_credit_account = account_title_db.get_default_credit_account()
        default_credit = "現金"
        if default_credit_account:
            name = default_credit_account.get("name", "")
            card_name = default_credit_account.get("card_name", "")
            last_four = default_credit_account.get("last_four_digits", "")
            if card_name and last_four:
                default_credit = f"{name} ({card_name} ****{last_four})"
            elif card_name:
                default_credit = f"{name} ({card_name})"
            elif name:
                default_credit = name

        receipts_for_journal = []
        dates_needed = set()
        for receipt in all_receipts:
            ocr_text = receipt.get('ocr_text') or ""
            if "保証書" in ocr_text or "保証期間" in ocr_text or "保証規定" in ocr_text:
                continue
            raw_purchase_date = (receipt.get('purchase_date', '') or '').strip()
            if not raw_purchase_date:
                continue
            purchase_datetime = raw_purchase_date.replace('T', ' ').strip()
            date_only = purchase_datetime.split(' ')[0]
            receipts_for_journal.append((receipt, purchase_datetime, date_only))
            dates_needed.add(date_only)

        entries_by_date = {}
        for d in dates_needed:
            entries_by_date[d] = journal_db.list_by_date(d, f"{d} 23:59:59")

        for idx, (receipt, purchase_datetime, purchase_date_only) in enumerate(receipts_for_journal, 1):
            tick(f"確定処理中... (仕訳帳登録: {idx}/{len(receipts_for_journal)})")
            try:
                receipt_id = receipt.get('id')
                total_amount = receipt.get('total_amount', 0) or 0
                if not total_amount:
                    continue

                account_title = (receipt.get('account_title') or '').strip() or default_debit
                store_code = (receipt.get('store_code') or '').strip()
                store_name = ''
                if store_code:
                    try:
                        store = self.store_db.get_store_by_code(store_code)
                        if store:
                            store_name = store.get('store_name', '') or ''
                    except Exception:
                        pass
                if not store_name:
                    store_name = receipt.get('store_name_raw', '') or receipt.get('store_name', '') or ''
                    if store_name:
                        store_name = re.sub(r'\s*\([^)]*\)', '', store_name)
                        store_name = re.sub(r'\s+ss-\d+', '', store_name, flags=re.IGNORECASE).strip()

                registration_number = receipt.get('registration_number', '') or ''
                image_url = receipt.get('gcs_url') or receipt.get('image_url') or ''
                day_entries = entries_by_date.get(purchase_date_only, [])

                existing_entry = None
                if image_url:
                    for e in day_entries:
                        if e.get('image_url') == image_url:
                            existing_entry = e
                            break
                if existing_entry is None:
                    for e in day_entries:
                        if e.get('amount') == total_amount and (e.get('description') or '') == store_name:
                            existing_entry = e
                            break

                journal_entry = {
                    "transaction_date": purchase_datetime,
                    "debit_account": account_title,
                    "amount": total_amount,
                    "credit_account": default_credit,
                    "description": store_name,
                    "invoice_number": registration_number,
                    "tax_category": "10％",
                    "image_url": image_url
                }

                if existing_entry and existing_entry.get('id'):
                    eid = existing_entry['id']
                    has_changes = (
                        existing_entry.get('transaction_date') != purchase_datetime or
                        existing_entry.get('debit_account') != account_title or
                        existing_entry.get('amount') != total_amount or
                        existing_entry.get('credit_account') != default_credit or
                        existing_entry.get('description') != store_name or
                        existing_entry.get('invoice_number') != registration_number or
                        existing_entry.get('tax_category') != "10％" or
                        existing_entry.get('image_url') != image_url
                    )
                    if has_changes:
                        journal_db.update(eid, journal_entry)
                        journal_count += 1
                        existing_entry.update(journal_entry)
                else:
                    new_id = journal_db.insert(journal_entry)
                    journal_count += 1
                    journal_entry["id"] = new_id
                    day_entries.append(journal_entry)
            except Exception as e:
                error_count += 1
                error_messages.append(f"仕訳帳登録/更新エラー (receipt_id={receipt.get('id')}): {str(e)}")
        checkpoints["journal_update"] = perf_counter()

        # ---- 5) 画面反映と結果表示 ----
        if (updated_count > 0 or warranty_updated_count > 0) and hasattr(self, 'product_widget') and self.product_widget:
            if hasattr(self.product_widget, 'save_purchase_snapshot'):
                try:
                    self.product_widget.save_purchase_snapshot()
                except Exception:
                    pass
            pw_ref = self.product_widget
            QTimer.singleShot(0, pw_ref.refresh_purchase_table_if_built)

        if hasattr(self, 'evidence_widget'):
            try:
                if hasattr(self.evidence_widget, 'journal_entry_widget'):
                    journal_widget = self.evidence_widget.journal_entry_widget
                    setattr(journal_widget, "_initial_data_loaded", False)
            except Exception:
                pass

        progress.setValue(total_steps)
        progress.close()

        receipt_count = updated_count
        warranty_count = warranty_updated_count

        if receipt_count == 0 and warranty_count == 0 and error_count == 0:
            QMessageBox.information(
                self, "確定",
                "確定するレコードがありませんでした。\n"
                "レシート一覧にSKUが紐付けられているレコードがあるか確認してください。"
            )
        elif error_count == 0:
            msg = f"{receipt_count} 件のSKUにレシート画像を設定しました。"
            if warranty_count > 0:
                msg += f"\n{warranty_count} 件のSKUに保証書情報（保証書画像・保証期間・保証最終日）を設定しました。"
            if journal_count > 0:
                msg += f"\n{journal_count} 件のレシートを仕訳帳に登録しました。"
            QMessageBox.information(self, "確定完了", msg)
        else:
            msg = f"{receipt_count} 件のSKUにレシート画像を設定しました。"
            if warranty_count > 0:
                msg += f"\n{warranty_count} 件のSKUに保証書情報（保証書画像・保証期間・保証最終日）を設定しました。"
            if journal_count > 0:
                msg += f"\n{journal_count} 件のレシートを仕訳帳に登録しました。"
            msg += f"\n\nエラー: {error_count} 件\n" + "\n".join(error_messages[:5])
            QMessageBox.warning(self, "確定完了（一部エラー）", msg)

        try:
            base_folder: Optional[Path] | None = None
            if getattr(self, "current_folder", None):
                base_folder = self.current_folder
            elif getattr(self, "default_folder", None):
                base_folder = self.default_folder
            route_id = mark_route_evidence_completed(
                folder_path=base_folder,
                receipts=all_receipts,
            )
            if route_id:
                print(f"[DEBUG] ルート証憑フラグを更新: route_id={route_id}")
        except Exception as e:
            print(f"証憑フラグ更新エラー: {e}")
        t_end = perf_counter()
        print(
            "[PERF] confirm_receipt_linkage optimized "
            f"total={t_end - t0:.3f}s, "
            f"receipt_collect={checkpoints.get('receipt_collect', t0) - t0:.3f}s, "
            f"warranty_collect={checkpoints.get('warranty_collect', checkpoints.get('receipt_collect', t0)) - checkpoints.get('receipt_collect', t0):.3f}s, "
            f"memory_update={checkpoints.get('memory_update', checkpoints.get('warranty_collect', t0)) - checkpoints.get('warranty_collect', t0):.3f}s, "
            f"product_db_update={checkpoints.get('product_db_update', checkpoints.get('memory_update', t0)) - checkpoints.get('memory_update', t0):.3f}s, "
            f"journal_update={checkpoints.get('journal_update', checkpoints.get('product_db_update', t0)) - checkpoints.get('product_db_update', t0):.3f}s"
        )

