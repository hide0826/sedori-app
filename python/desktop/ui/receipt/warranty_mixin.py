#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保証書テーブル mixin。"""
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


class ReceiptWarrantyMixin:
    def on_warranty_selection_changed(self):
        """保証書表の選択変更を監視"""
        if not hasattr(self, 'delete_warranty_row_btn'):
            return
        selection_model = self.warranty_table.selectionModel()
        has_selection = bool(selection_model and selection_model.selectedRows())
        self.delete_warranty_row_btn.setEnabled(has_selection)

    def delete_selected_warranties(self):
        """選択した保証書を削除"""
        selection_model = self.warranty_table.selectionModel()
        if not selection_model:
            return
        rows = selection_model.selectedRows()
        if not rows:
            QMessageBox.information(self, "情報", "削除する保証書を選択してください。")
            return
        receipt_ids = []
        for idx in rows:
            item = self.warranty_table.item(idx.row(), 0)
            if item:
                try:
                    receipt_ids.append(int(item.text()))
                except ValueError:
                    continue
        if not receipt_ids:
            QMessageBox.warning(self, "警告", "選択された行に有効なIDがありません。")
            return
        if QMessageBox.question(
            self,
            "確認",
            f"選択された {len(receipt_ids)} 件の保証書を削除します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        ) != QMessageBox.Yes:
            return
        deleted = 0
        for rid in receipt_ids:
            if self.receipt_db.delete_receipt_by_id(rid):
                deleted += 1
                if self.current_receipt_id == rid:
                    self.reset_form()
        self.refresh_receipt_list()
        QMessageBox.information(self, "削除完了", f"{deleted} 件の保証書を削除しました。")

    def on_warranty_table_context_menu(self, position):
        """保証書テーブルの右クリックメニュー"""
        item = self.warranty_table.itemAt(position)
        if not item:
            return
        
        row = item.row()
        id_item = self.warranty_table.item(row, 0)
        if not id_item:
            return
        
        menu = QMenu(self)
        
        # コピー機能
        copy_action = menu.addAction("コピー")
        copy_action.triggered.connect(lambda: self.copy_warranty_cell(row, item.column()))
        
        menu.addSeparator()
        
        # コピーを追加メニュー（同一保証書内に複数SKU・複数保証期間があった場合に保証期間別にDBに紐付ける為）
        copy_add_action = menu.addAction("コピーを追加")
        copy_add_action.triggered.connect(lambda: self.copy_add_warranty_row(row))
        
        # 商品の追加メニュー
        add_product_action = menu.addAction("商品の追加")
        add_product_action.triggered.connect(lambda: self.add_warranty_product_row(row))
        
        menu.exec_(self.warranty_table.viewport().mapToGlobal(position))
    
    def add_warranty_product_row(self, source_row: int):
        """選択行の種別〜店舗コードをコピーして新しい行を追加"""
        if not hasattr(self, 'warranty_table'):
            return
        
        # 元の行からデータを取得（列1〜6をコピー）
        # 列インデックス: 0=ID, 1=種別, 2=画像ファイル名, 3=日付, 4=店舗名, 5=電話番号, 6=店舗コード
        source_items = {}
        for col in range(1, 7):  # 列1〜6
            item = self.warranty_table.item(source_row, col)
            if item:
                source_items[col] = item.text()
            else:
                widget = self.warranty_table.cellWidget(source_row, col)
                if widget:
                    # ウィジェットの場合はテキストを取得できないので、対応する列のデータを別途取得
                    pass
        
        # 店舗コード列のデータを取得（UserRoleに保存されている）
        store_code_item = self.warranty_table.item(source_row, 6)
        store_code = ""
        store_label = ""
        if store_code_item:
            store_code = store_code_item.data(Qt.UserRole) or ""
            store_label = store_code_item.text() or ""
        
        # ID列を取得（receipt_idを取得するため）
        id_item = self.warranty_table.item(source_row, 0)
        receipt_id = None
        if id_item:
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                pass
        
        # receiptデータを取得（店舗名や電話番号などの詳細情報を取得するため）
        receipt = None
        if receipt_id:
            receipt = self.receipt_db.get_receipt(receipt_id)
        
        # 新しい行を追加
        self.warranty_table.blockSignals(True)
        new_row = self.warranty_table.rowCount()
        self.warranty_table.insertRow(new_row)
        
        # ID列:
        # 「商品の追加」は“同じ保証書画像に紐づく別商品の行”を作る用途なので、
        # ここでは元のreceipt_idをコピーしない（コピーするとDB保存がスキップされ、再起動で消える）。
        # 空IDにしておき、最後にsave_warranty_row_to_db()で新しいreceiptレコードを作成してIDを採番する。
        self.warranty_table.setItem(new_row, 0, QTableWidgetItem(""))
        
        # 種別（列1）
        doc_type_item = self.warranty_table.item(source_row, 1)
        if doc_type_item:
            self.warranty_table.setItem(new_row, 1, QTableWidgetItem(doc_type_item.text()))
        
        # 画像ファイル名（列2）
        image_item = self.warranty_table.item(source_row, 2)
        if image_item:
            self.warranty_table.setItem(new_row, 2, QTableWidgetItem(image_item.text()))
        
        # 日付（列3）
        date_item = self.warranty_table.item(source_row, 3)
        if date_item:
            self.warranty_table.setItem(new_row, 3, QTableWidgetItem(date_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 3, QTableWidgetItem(receipt.get('purchase_date') or ""))
        
        # 店舗名（列4）
        store_name_item = self.warranty_table.item(source_row, 4)
        if store_name_item:
            self.warranty_table.setItem(new_row, 4, QTableWidgetItem(store_name_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 4, QTableWidgetItem(receipt.get('store_name_raw') or ""))
        
        # 電話番号（列5）
        phone_item = self.warranty_table.item(source_row, 5)
        if phone_item:
            self.warranty_table.setItem(new_row, 5, QTableWidgetItem(phone_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 5, QTableWidgetItem(receipt.get('phone_number') or ""))
        
        # 店舗コード（列6）
        if store_code or store_label:
            store_item = QTableWidgetItem(store_label if store_label else store_code)
            store_item.setData(Qt.UserRole, store_code)
            self.warranty_table.setItem(new_row, 6, store_item)
        elif receipt:
            store_code_from_receipt = receipt.get('store_code') or ""
            store_label_from_receipt = self._format_store_code_label(
                store_code_from_receipt, 
                receipt.get('store_name_raw') or ""
            )
            store_item = QTableWidgetItem(store_label_from_receipt)
            store_item.setData(Qt.UserRole, store_code_from_receipt)
            self.warranty_table.setItem(new_row, 6, store_item)
        
        # SKU・商品名（列7, 8）: 空欄でプルダウンを設定
        if receipt:
            self._populate_warranty_product_cell(new_row, receipt, "", "")
        else:
            # receiptがない場合でも、テーブルのデータから最低限のreceiptオブジェクトを作成
            minimal_receipt = {
                'purchase_date': date_item.text() if date_item else "",
                'store_code': store_code,
                'store_name_raw': store_name_item.text() if store_name_item else "",
            }
            self._populate_warranty_product_cell(new_row, minimal_receipt, "", "")
        
        # 保証期間(日)（列9）: 空欄
        self.warranty_table.setItem(new_row, 9, QTableWidgetItem(""))
        
        # 保証最終日（列10）: 日付をデフォルトに設定
        from PySide6.QtWidgets import QDateEdit
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        
        # 日付列から日付を取得してデフォルトに設定
        date_item = self.warranty_table.item(new_row, 3)
        if date_item:
            purchase_date_str = date_item.text().strip().replace("/", "-").split(" ")[0]
            if purchase_date_str:
                try:
                    from datetime import datetime
                    qdate = QDate.fromString(purchase_date_str, "yyyy-MM-dd")
                    if qdate.isValid():
                        date_edit.setDate(qdate)
                except Exception:
                    pass
        
        self.warranty_table.setCellWidget(new_row, 10, date_edit)
        
        # 日付変更時の処理を接続
        date_edit.dateChanged.connect(lambda qd, r=new_row: self.on_warranty_date_changed(r, qd))
        
        self.warranty_table.blockSignals(False)
        
        # 新しい行を選択状態にする
        self.warranty_table.selectRow(new_row)
        
        # データベースに新しいレシートレコードを作成（永続化のため）
        self.save_warranty_row_to_db(new_row)
    
    def copy_add_warranty_row(self, source_row: int):
        """選択行を完全にコピーして新しい行を追加（同一保証書内に複数SKU・複数保証期間があった場合に保証期間別にDBに紐付ける為）"""
        if not hasattr(self, 'warranty_table'):
            return
        
        # ID列を取得（receipt_idを取得するため）
        id_item = self.warranty_table.item(source_row, 0)
        receipt_id = None
        if id_item:
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                pass
        
        # receiptデータを取得
        receipt = None
        if receipt_id:
            receipt = self.receipt_db.get_receipt(receipt_id)
        
        # 新しい行を追加
        self.warranty_table.blockSignals(True)
        new_row = self.warranty_table.rowCount()
        self.warranty_table.insertRow(new_row)
        
        # ID列: 空IDにしておき、最後にsave_warranty_row_to_db()で新しいreceiptレコードを作成してIDを採番する
        self.warranty_table.setItem(new_row, 0, QTableWidgetItem(""))
        
        # 種別（列1）
        doc_type_item = self.warranty_table.item(source_row, 1)
        if doc_type_item:
            self.warranty_table.setItem(new_row, 1, QTableWidgetItem(doc_type_item.text()))
        
        # 画像ファイル名（列2）
        image_item = self.warranty_table.item(source_row, 2)
        if image_item:
            self.warranty_table.setItem(new_row, 2, QTableWidgetItem(image_item.text()))
        
        # 日付（列3）
        date_item = self.warranty_table.item(source_row, 3)
        if date_item:
            self.warranty_table.setItem(new_row, 3, QTableWidgetItem(date_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 3, QTableWidgetItem(receipt.get('purchase_date') or ""))
        
        # 店舗名（列4）
        store_name_item = self.warranty_table.item(source_row, 4)
        if store_name_item:
            self.warranty_table.setItem(new_row, 4, QTableWidgetItem(store_name_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 4, QTableWidgetItem(receipt.get('store_name_raw') or ""))
        
        # 電話番号（列5）
        phone_item = self.warranty_table.item(source_row, 5)
        if phone_item:
            self.warranty_table.setItem(new_row, 5, QTableWidgetItem(phone_item.text()))
        elif receipt:
            self.warranty_table.setItem(new_row, 5, QTableWidgetItem(receipt.get('phone_number') or ""))
        
        # 店舗コード（列6）
        store_code_item = self.warranty_table.item(source_row, 6)
        if store_code_item:
            store_code = store_code_item.data(Qt.UserRole) or ""
            store_label = store_code_item.text() or ""
            store_item = QTableWidgetItem(store_label if store_label else store_code)
            store_item.setData(Qt.UserRole, store_code)
            self.warranty_table.setItem(new_row, 6, store_item)
        elif receipt:
            store_code_from_receipt = receipt.get('store_code') or ""
            store_label_from_receipt = self._format_store_code_label(
                store_code_from_receipt, 
                receipt.get('store_name_raw') or ""
            )
            store_item = QTableWidgetItem(store_label_from_receipt)
            store_item.setData(Qt.UserRole, store_code_from_receipt)
            self.warranty_table.setItem(new_row, 6, store_item)
        
        # SKU・商品名（列7, 8）: 元の行からコピー
        sku_item = self.warranty_table.item(source_row, 7)
        product_item = self.warranty_table.item(source_row, 8)
        sku_text = sku_item.text() if sku_item else ""
        product_name_text = product_item.text() if product_item else ""
        
        # SKUと商品名をコピーしてプルダウンを設定
        if receipt:
            # receipt_dataを更新（SKUと商品名を含める）
            receipt_data = dict(receipt)
            receipt_data['sku'] = sku_text
            receipt_data['product_name'] = product_name_text
            self._populate_warranty_product_cell(new_row, receipt_data, sku_text, product_name_text)
        else:
            # receiptがない場合でも、テーブルのデータから最低限のreceiptオブジェクトを作成
            date_item = self.warranty_table.item(new_row, 3)
            store_code_item = self.warranty_table.item(new_row, 6)
            store_name_item = self.warranty_table.item(new_row, 4)
            store_code = store_code_item.data(Qt.UserRole) if store_code_item else ""
            minimal_receipt = {
                'purchase_date': date_item.text() if date_item else "",
                'store_code': store_code,
                'store_name_raw': store_name_item.text() if store_name_item else "",
                'sku': sku_text,
                'product_name': product_name_text,
            }
            self._populate_warranty_product_cell(new_row, minimal_receipt, sku_text, product_name_text)
        
        # 保証期間(日)（列9）: 元の行からコピー
        days_item = self.warranty_table.item(source_row, 9)
        if days_item:
            self.warranty_table.setItem(new_row, 9, QTableWidgetItem(days_item.text()))
        else:
            self.warranty_table.setItem(new_row, 9, QTableWidgetItem(""))
        
        # 保証最終日（列10）: 元の行からコピー
        warranty_until_widget = self.warranty_table.cellWidget(source_row, 10)
        from PySide6.QtWidgets import QDateEdit
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        
        if warranty_until_widget and isinstance(warranty_until_widget, QDateEdit):
            # 元の行の保証最終日をコピー
            source_date = warranty_until_widget.date()
            if source_date.isValid():
                date_edit.setDate(source_date)
        else:
            # 元の行に保証最終日がない場合は、日付列から日付を取得してデフォルトに設定
            date_item = self.warranty_table.item(new_row, 3)
            if date_item:
                purchase_date_str = date_item.text().strip().replace("/", "-").split(" ")[0]
                if purchase_date_str:
                    try:
                        from datetime import datetime
                        qdate = QDate.fromString(purchase_date_str, "yyyy-MM-dd")
                        if qdate.isValid():
                            date_edit.setDate(qdate)
                    except Exception:
                        pass
        
        self.warranty_table.setCellWidget(new_row, 10, date_edit)
        
        # 日付変更時の処理を接続
        date_edit.dateChanged.connect(lambda qd, r=new_row: self.on_warranty_date_changed(r, qd))
        
        self.warranty_table.blockSignals(False)
        
        # 新しい行を選択状態にする
        self.warranty_table.selectRow(new_row)
        
        # データベースに新しいレシートレコードを作成（永続化のため）
        self.save_warranty_row_to_db(new_row)
        
        # 新しいレシートレコードにSKUと保証期間の情報を保存
        id_item = self.warranty_table.item(new_row, 0)
        if id_item:
            try:
                new_receipt_id = int(id_item.text())
                if new_receipt_id:
                    # SKU情報を取得（カンマ区切りの複数SKUに対応）
                    sku_item = self.warranty_table.item(new_row, 7)
                    sku_text = sku_item.text() if sku_item else ""
                    
                    # 保証期間(日)を取得
                    days_item = self.warranty_table.item(new_row, 9)
                    warranty_days = 0
                    if days_item and days_item.text():
                        try:
                            warranty_days = int(days_item.text())
                        except ValueError:
                            pass
                    
                    # 保証最終日を取得
                    warranty_until_widget = self.warranty_table.cellWidget(new_row, 10)
                    warranty_until_str = None
                    if warranty_until_widget and isinstance(warranty_until_widget, QDateEdit):
                        warranty_until = warranty_until_widget.date()
                        if warranty_until.isValid():
                            warranty_until_str = warranty_until.toString("yyyy-MM-dd")
                    
                    # 商品名を取得
                    product_item = self.warranty_table.item(new_row, 8)
                    product_name = product_item.text() if product_item else ""
                    
                    # 更新データを準備
                    updates = {}
                    if sku_text:
                        # カンマ区切りのSKUをlinked_skusに保存
                        linked_skus = [sku.strip() for sku in sku_text.split(',') if sku.strip()]
                        if linked_skus:
                            updates['linked_skus'] = ','.join(linked_skus)
                            # 最初のSKUをskuフィールドにも保存（後方互換性のため）
                            updates['sku'] = linked_skus[0]
                    if product_name:
                        updates['product_name'] = product_name
                    if warranty_days > 0:
                        updates['warranty_days'] = warranty_days
                    if warranty_until_str:
                        updates['warranty_until'] = warranty_until_str
                    
                    # データベースを更新
                    if updates:
                        self.receipt_db.update_receipt(new_receipt_id, updates)
            except (ValueError, Exception) as e:
                # エラーが発生しても処理を続行
                print(f"保証書コピー追加時のSKU/保証期間保存エラー: {e}")
    
    def copy_warranty_cell(self, row: int, col: int):
        """保証書テーブルのセルをクリップボードにコピー"""
        if not hasattr(self, 'warranty_table'):
            return
        
        # セルのテキストを取得
        item = self.warranty_table.item(row, col)
        if item:
            text = item.text()
        else:
            # ウィジェットの場合はテキストを取得
            widget = self.warranty_table.cellWidget(row, col)
            if widget:
                if hasattr(widget, 'text'):
                    text = widget.text()
                elif hasattr(widget, 'currentText'):
                    text = widget.currentText()
                elif hasattr(widget, 'date'):
                    qdate = widget.date()
                    if qdate.isValid():
                        text = qdate.toString("yyyy-MM-dd")
                    else:
                        text = ""
                else:
                    text = ""
            else:
                text = ""
        
        # クリップボードにコピー
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
    
    def save_warranty_row_to_db(self, row: int):
        """保証書テーブルの行をデータベースに保存"""
        if not hasattr(self, 'warranty_table'):
            return
        
        try:
            # テーブルからデータを取得
            id_item = self.warranty_table.item(row, 0)
            if not id_item:
                return
            
            # 既存のreceipt_idがある場合は、基本的に新規作成しない（既存行の再保存を避ける）
            receipt_id = None
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                pass
            
            # receipt_idが既に入っている行はここでは新規作成しない
            # （SKU/商品名/保証期間などの編集は別ロジックでupdate_receiptされる）
            if receipt_id:
                return
            
            # テーブルからデータを取得
            doc_type_item = self.warranty_table.item(row, 1)
            image_item = self.warranty_table.item(row, 2)
            date_item = self.warranty_table.item(row, 3)
            store_name_item = self.warranty_table.item(row, 4)
            phone_item = self.warranty_table.item(row, 5)
            store_code_item = self.warranty_table.item(row, 6)
            
            # 店舗コードを取得
            store_code = ""
            if store_code_item:
                store_code = store_code_item.data(Qt.UserRole) or ""
                if not store_code:
                    store_code = store_code_item.text().split(" ")[0] if store_code_item.text() else ""
            
            # 画像ファイル名を取得
            image_file_name = image_item.text() if image_item else ""

            # file_path/original_file_path は可能なら既存レコードから実パスを引き継ぐ（ファイル名だけだと起動後に画像が開けない）
            resolved_file_path = image_file_name
            resolved_original_file_path = image_file_name
            try:
                existing_by_name = self.receipt_db.find_by_file_name(image_file_name)
                if existing_by_name:
                    resolved_file_path = existing_by_name.get("file_path") or resolved_file_path
                    resolved_original_file_path = existing_by_name.get("original_file_path") or resolved_original_file_path
            except Exception:
                pass
            
            # 新しいレシートレコードを作成
            receipt_data = {
                "file_path": resolved_file_path,
                "original_file_path": resolved_original_file_path,
                "purchase_date": date_item.text() if date_item else "",
                "store_name_raw": store_name_item.text() if store_name_item else "",
                "phone_number": phone_item.text() if phone_item else "",
                "store_code": store_code,
                "ocr_text": "保証書",  # 保証書として識別
                "total_amount": 0,
                "items_count": 0,
            }
            
            # データベースに保存
            new_receipt_id = self.receipt_db.insert_receipt(receipt_data)
            
            # テーブルのID列を更新
            if new_receipt_id:
                self.warranty_table.setItem(row, 0, QTableWidgetItem(str(new_receipt_id)))
            
        except Exception as e:
            import traceback
            print(f"保証書行の保存エラー: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "警告", f"保証書行の保存に失敗しました:\n{e}")

    def on_warranty_item_double_clicked(self, item: QTableWidgetItem):
        """保証書一覧のダブルクリック動作（画像ファイル名をダブルクリックで保証書編集ダイアログを開く）"""
        row = item.row()
        col = item.column()
        # 画像ファイル名列のみ対象
        if col != 2:
            return
        id_item = self.warranty_table.item(row, 0)
        if not id_item:
            return
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            return
        # 保証書編集ダイアログを表示
        self._show_warranty_edit_dialog(receipt_id, row)

    def _show_warranty_edit_dialog(self, receipt_id: int, table_row: int):
        """保証書編集ダイアログを表示（画像表示 + 保証期間・保証最終日編集）"""
        from pathlib import Path
        
        # レシートデータを取得
        receipt = self.receipt_db.get_receipt(receipt_id)
        if not receipt:
            QMessageBox.warning(self, "警告", "保証書データが見つかりません。")
            return
        
        # 画像ファイルパスを取得
        image_path = receipt.get('file_path') or receipt.get('original_file_path')
        if not image_path:
            QMessageBox.warning(self, "警告", "画像ファイルパスが見つかりません。")
            return
        
        image_file = Path(image_path)
        if not image_file.exists():
            QMessageBox.warning(self, "警告", f"画像ファイルが存在しません:\n{image_path}")
            return
        
        # 元の画像を読み込み（回転状態を保持するため）
        original_pixmap = QPixmap(str(image_file))
        if original_pixmap.isNull():
            QMessageBox.warning(self, "警告", "画像を読み込めませんでした。")
            return
        
        # 現在の回転角度を保持（0度から開始）
        current_rotation = [0]  # リストで保持して参照渡しにする
        
        # ダイアログ作成
        dialog = QDialog(self)
        dialog.setWindowTitle("保証書編集")
        dialog.setMinimumSize(1200, 800)
        
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
            
            # 保証書一覧を更新（サムネイルが更新される可能性があるため）
            if hasattr(self, 'refresh_receipt_list'):
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
        
        # 右側：保証書編集パネル
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        
        # 編集フォーム
        form_group = QGroupBox("保証書編集")
        form_layout = QFormLayout(form_group)
        
        # 日付
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        purchase_date = receipt.get('purchase_date')
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
        
        # 保証期間(日)
        warranty_days_edit = QSpinBox()
        warranty_days_edit.setMinimum(0)
        warranty_days_edit.setMaximum(9999)
        warranty_days = receipt.get('warranty_days')
        if warranty_days:
            try:
                warranty_days_edit.setValue(int(warranty_days))
            except (ValueError, TypeError):
                warranty_days_edit.setValue(0)
        else:
            warranty_days_edit.setValue(0)
        form_layout.addRow("保証期間(日):", warranty_days_edit)
        
        # 保証最終日（デフォルトは日付と同じ）
        warranty_until_edit = QDateEdit()
        warranty_until_edit.setCalendarPopup(True)
        
        # 日付を取得
        purchase_date_val = date_edit.date()
        purchase_date_str = purchase_date.replace("/", "-").split(" ")[0] if purchase_date else ""
        
        # デフォルトは日付と同じ
        default_until_date = purchase_date_val if purchase_date_val.isValid() else QDate.currentDate()
        
        # 保証期間が0または未設定の場合は、日付と同じにする
        if not warranty_days or warranty_days == 0:
            warranty_until_edit.setDate(default_until_date)
        else:
            # 保証期間がある場合は日付+保証期間で計算
            if purchase_date_str:
                try:
                    from datetime import datetime, timedelta
                    base = datetime.strptime(purchase_date_str, "%Y-%m-%d")
                    until_date = QDate.fromString(
                        (base + timedelta(days=int(warranty_days))).strftime("%Y-%m-%d"),
                        "yyyy-MM-dd",
                    )
                    if until_date.isValid():
                        # 既存のwarranty_untilが有効な値で、かつ保証期間と一致する場合のみ使用
                        warranty_until = receipt.get('warranty_until')
                        if warranty_until:
                            try:
                                existing_until = QDate.fromString(warranty_until, "yyyy-MM-dd")
                                # 既存の値が有効で、かつ計算値と一致する場合のみ使用
                                if existing_until.isValid() and existing_until == until_date:
                                    warranty_until_edit.setDate(existing_until)
                                else:
                                    warranty_until_edit.setDate(until_date)
                            except Exception:
                                warranty_until_edit.setDate(until_date)
                        else:
                            warranty_until_edit.setDate(until_date)
                    else:
                        warranty_until_edit.setDate(default_until_date)
                except Exception:
                    warranty_until_edit.setDate(default_until_date)
            else:
                warranty_until_edit.setDate(default_until_date)
        
        form_layout.addRow("保証最終日:", warranty_until_edit)
        
        # 店舗名（プルダウンで店舗コード＋店舗名を選択可能）
        store_name_combo = QComboBox()
        store_name_combo.setEditable(False)
        
        def load_store_combo():
            """店舗名プルダウンを読み込む（日付に基づいて優先店舗を表示）"""
            # 現在選択されている店舗コードを保持
            current_selected_code = store_name_combo.currentData() if store_name_combo.count() > 0 else None
            if not current_selected_code:
                current_selected_code = receipt.get('store_code', '') or ''
            
            # プルダウンをクリア
            store_name_combo.clear()
            
            # 現在の日付を取得
            purchase_date_val = date_edit.date()
            purchase_date_str = purchase_date_val.toString("yyyy-MM-dd") if purchase_date_val.isValid() else ""
            
            print(f"[保証書編集] 店舗名プルダウン読み込み: 日付={purchase_date_str}")
            
            # 仕入DBから同じ日付の店舗コードを取得（優先表示用）
            priority_store_codes = set()
            if self.product_widget and purchase_date_str:
                try:
                    from datetime import datetime
                    purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                    if not purchase_records:
                        print(f"[保証書編集] 仕入DBにレコードがありません")
                    else:
                        print(f"[保証書編集] 仕入DBレコード数: {len(purchase_records)}")
                    
                    receipt_date_obj = None
                    try:
                        receipt_date_obj = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
                        print(f"[保証書編集] 比較対象日付: {receipt_date_obj}")
                    except Exception as e:
                        print(f"[保証書編集] 日付パースエラー: {e}")
                    
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
                                            print(f"[保証書編集] 優先店舗コード追加: {store_code_clean} (元の値: {record_store_code}, 日付: {original_record_date_str})")
                            except Exception:
                                continue
                        print(f"[保証書編集] 日付一致レコード数: {matched_count}, 優先店舗コード数: {len(priority_store_codes)}")
                except Exception as e:
                    import traceback
                    print(f"[保証書編集] 店舗コード取得エラー: {e}\n{traceback.format_exc()}")
            
            # 店舗マスタから全店舗を読み込み
            try:
                stores = self.store_db.list_stores()
                print(f"[保証書編集] 店舗マスタ数: {len(stores)}")
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
                        print(f"[保証書編集] 優先店舗追加: {label} (コード: {code})")
                    else:
                        other_stores.append((label, code))
                
                print(f"[保証書編集] 優先店舗数: {len(priority_stores)}, 通常店舗数: {len(other_stores)}")
                
                # 優先店舗を先に追加
                for label, code in priority_stores:
                    store_name_combo.addItem(label, code)
                
                # 優先店舗と通常店舗の間に区切りを追加（優先店舗がある場合のみ）
                if priority_stores and other_stores:
                    store_name_combo.insertSeparator(store_name_combo.count())
                
                # 通常店舗を追加
                for label, code in other_stores:
                    store_name_combo.addItem(label, code)
                
                print(f"[保証書編集] プルダウン項目数: {store_name_combo.count()}")
                
                # 以前選択されていた店舗コードに一致する項目を選択
                if current_selected_code:
                    idx = store_name_combo.findData(current_selected_code)
                    if idx >= 0:
                        store_name_combo.setCurrentIndex(idx)
                        print(f"[保証書編集] 以前の選択を復元: {current_selected_code} (インデックス: {idx})")
                    else:
                        print(f"[保証書編集] 以前の選択が見つかりません: {current_selected_code}")
            except Exception as e:
                import traceback
                print(f"[保証書編集] 店舗マスタ読み込みエラー: {e}\n{traceback.format_exc()}")
        
        # 初期読み込み
        load_store_combo()
        
        # 日付変更時に店舗名プルダウンを再読み込み
        date_edit.dateChanged.connect(load_store_combo)
        form_layout.addRow("店舗名:", store_name_combo)
        
        # 店舗コード（店舗名コンボボックスと連動）
        store_code_display = QLineEdit()
        store_code_display.setReadOnly(True)
        current_store_code = receipt.get('store_code', '') or ''
        store_code_display.setText(current_store_code)
        form_layout.addRow("店舗コード:", store_code_display)
        
        # 店舗名コンボボックスの変更時に店舗コード表示を更新
        def update_store_code_display():
            selected_code = store_name_combo.currentData()
            store_code_display.setText(selected_code if selected_code else '')
        store_name_combo.currentIndexChanged.connect(update_store_code_display)
        
        # 保証期間と保証最終日の相互連動
        def on_warranty_days_changed(value: int):
            """保証期間変更時に保証最終日を更新"""
            purchase_date_val = date_edit.date()
            if purchase_date_val.isValid():
                if value > 0:
                    from datetime import datetime, timedelta
                    try:
                        date_str = purchase_date_val.toString("yyyy-MM-dd")
                        base = datetime.strptime(date_str, "%Y-%m-%d")
                        final_date = base + timedelta(days=value)
                        final_qdate = QDate.fromString(final_date.strftime("%Y-%m-%d"), "yyyy-MM-dd")
                        if final_qdate.isValid():
                            warranty_until_edit.blockSignals(True)
                            warranty_until_edit.setDate(final_qdate)
                            warranty_until_edit.blockSignals(False)
                    except Exception:
                        pass
                else:
                    # 保証期間が0の場合は日付と同じにする
                    warranty_until_edit.blockSignals(True)
                    warranty_until_edit.setDate(purchase_date_val)
                    warranty_until_edit.blockSignals(False)
        
        def on_warranty_until_changed(qdate: QDate):
            """保証最終日変更時に保証期間を更新"""
            purchase_date_val = date_edit.date()
            if purchase_date_val.isValid() and qdate.isValid():
                from datetime import datetime
                try:
                    purchase_str = purchase_date_val.toString("yyyy-MM-dd")
                    until_str = qdate.toString("yyyy-MM-dd")
                    purchase_dt = datetime.strptime(purchase_str, "%Y-%m-%d")
                    until_dt = datetime.strptime(until_str, "%Y-%m-%d")
                    days = (until_dt - purchase_dt).days
                    if days >= 0:
                        warranty_days_edit.blockSignals(True)
                        warranty_days_edit.setValue(days)
                        warranty_days_edit.blockSignals(False)
                except Exception:
                    pass
        
        warranty_days_edit.valueChanged.connect(on_warranty_days_changed)
        warranty_until_edit.dateChanged.connect(on_warranty_until_changed)
        
        # 日付変更時に保証最終日を更新（保証期間がある場合は日付+保証期間で計算）
        def on_date_changed(qdate: QDate):
            """日付変更時に保証最終日を更新"""
            if qdate.isValid():
                warranty_days_val = warranty_days_edit.value()
                if warranty_days_val > 0:
                    from datetime import datetime, timedelta
                    try:
                        date_str = qdate.toString("yyyy-MM-dd")
                        base = datetime.strptime(date_str, "%Y-%m-%d")
                        final_date = base + timedelta(days=warranty_days_val)
                        final_qdate = QDate.fromString(final_date.strftime("%Y-%m-%d"), "yyyy-MM-dd")
                        if final_qdate.isValid():
                            warranty_until_edit.blockSignals(True)
                            warranty_until_edit.setDate(final_qdate)
                            warranty_until_edit.blockSignals(False)
                    except Exception:
                        pass
                else:
                    # 保証期間が0の場合は日付と同じにする
                    warranty_until_edit.blockSignals(True)
                    warranty_until_edit.setDate(qdate)
                    warranty_until_edit.blockSignals(False)
        
        date_edit.dateChanged.connect(on_date_changed)
        
        right_layout.addWidget(form_group)
        
        # SKU紐付けセクション
        sku_group = QGroupBox("紐付けSKU")
        sku_layout = QVBoxLayout(sku_group)
        
        # 現在の紐付けSKUリスト
        linked_skus_list = QListWidget()
        linked_skus_list.setMaximumHeight(150)
        linked_skus_text = receipt.get('linked_skus', '') or ''
        
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
                    
                    sku_info_map[sku] = {'price': total_amount, 'time': time_str}
        
        # 既存の紐付けSKUを表示
        if linked_skus_text:
            linked_skus = [sku.strip() for sku in linked_skus_text.split(',') if sku.strip()]
            for sku in linked_skus:
                if sku in sku_info_map:
                    info = sku_info_map[sku]
                    display_text = f"{sku} - ¥{int(info['price']):,} - ({info['time']})"
                else:
                    display_text = sku
                item = linked_skus_list.addItem(display_text)
                list_item = linked_skus_list.item(linked_skus_list.count() - 1)
                if list_item:
                    list_item.setData(Qt.UserRole, sku)
        
        sku_layout.addWidget(linked_skus_list)
        
        # SKU削除ボタン
        remove_sku_btn = QPushButton("選択SKUを削除")
        remove_sku_btn.clicked.connect(lambda: self._remove_sku_from_list(linked_skus_list, None))
        sku_layout.addWidget(remove_sku_btn)
        
        # 仕入DBから候補SKUを取得
        candidate_skus_list = QListWidget()
        candidate_skus_list.setMaximumHeight(150)
        candidate_skus_list.setSelectionMode(QListWidget.MultiSelection)
        sku_layout.addWidget(QLabel("仕入DBの候補SKU:"))
        sku_layout.addWidget(candidate_skus_list)

        def load_candidate_skus():
            existing_skus = set()
            for i in range(linked_skus_list.count()):
                item = linked_skus_list.item(i)
                if not item:
                    continue
                sku = item.data(Qt.UserRole)
                if sku:
                    existing_skus.add(str(sku))
            purchase_date_val = date_edit.date()
            purchase_date_str = purchase_date_val.toString("yyyy-MM-dd") if purchase_date_val.isValid() else None
            store_code_val = store_name_combo.currentData() or store_name_combo.currentText() or ""
            self._populate_candidate_sku_list(
                candidate_skus_list,
                receipt,
                existing_skus,
                purchase_date_str=purchase_date_str,
                store_code=store_code_val,
            )

        load_candidate_skus()
        
        # 日付や店舗コードが変更されたときに候補SKUを再読み込み
        def reload_candidate_skus():
            load_candidate_skus()
        date_edit.dateChanged.connect(reload_candidate_skus)
        store_name_combo.currentIndexChanged.connect(reload_candidate_skus)
        
        # SKU追加ボタン
        add_sku_btn = QPushButton("選択SKUを追加")
        add_sku_btn.clicked.connect(lambda: self._add_skus_to_list(candidate_skus_list, linked_skus_list, None))
        sku_layout.addWidget(add_sku_btn)
        
        # SKU直接入力エリア
        sku_input_layout = QHBoxLayout()
        sku_input_label = QLabel("SKU直接入力:")
        sku_input_layout.addWidget(sku_input_label)
        
        sku_input_edit = QLineEdit()
        sku_input_edit.setPlaceholderText("SKUを入力（カンマ区切りで複数可）")
        sku_input_edit.returnPressed.connect(lambda: self._add_sku_by_input(sku_input_edit, linked_skus_list, None, sku_info_map))
        sku_input_layout.addWidget(sku_input_edit)
        
        sku_input_btn = QPushButton("追加")
        sku_input_btn.clicked.connect(lambda: self._add_sku_by_input(sku_input_edit, linked_skus_list, None, sku_info_map))
        sku_input_layout.addWidget(sku_input_btn)
        
        sku_layout.addLayout(sku_input_layout)
        
        right_layout.addWidget(sku_group)
        
        # ボタン
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(lambda: self._save_warranty_edit(
            dialog, receipt_id, table_row, date_edit.date(), 
            warranty_days_edit.value(), warranty_until_edit.date(),
            store_name_combo, linked_skus_list
        ))
        button_box.rejected.connect(dialog.reject)
        right_layout.addWidget(button_box)
        
        main_layout.addWidget(right_widget, 1)
        
        dialog.exec()
    
    def _save_warranty_edit(self, dialog: QDialog, receipt_id: int, table_row: int, 
                           purchase_date: QDate, warranty_days: int, warranty_until: QDate,
                           store_name_combo: QComboBox, linked_skus_list: QListWidget):
        """保証書編集を保存"""
        try:
            # 日付を文字列に変換
            purchase_date_str = purchase_date.toString("yyyy-MM-dd") if purchase_date.isValid() else None
            warranty_until_str = warranty_until.toString("yyyy-MM-dd") if warranty_until.isValid() else None
            
            # 店舗コードを取得
            store_code = store_name_combo.currentData() if store_name_combo else None
            store_code_str = store_code if store_code else None
            
            # 紐付けSKUを取得
            linked_skus = []
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
                        linked_skus.append(sku)
            
            # 紐付けSKUの最初のSKUから商品名を取得
            first_sku = None
            product_name = ""
            if linked_skus:
                first_sku = linked_skus[0]
                if self.product_widget:
                    purchase_records = getattr(self.product_widget, 'purchase_all_records', [])
                    for record in purchase_records:
                        record_sku = record.get('SKU') or record.get('sku', '')
                        if record_sku and record_sku.strip() == first_sku:
                            product_name = record.get('商品名') or record.get('product_name') or record.get('title') or ''
                            break
            
            # データベースを更新
            updates = {}
            if purchase_date_str:
                updates['purchase_date'] = purchase_date_str
            if warranty_days > 0:
                updates['warranty_days'] = warranty_days
            if warranty_until_str:
                updates['warranty_until'] = warranty_until_str
            if store_code_str:
                updates['store_code'] = store_code_str
            if linked_skus:
                updates['linked_skus'] = ','.join(linked_skus)
            else:
                updates['linked_skus'] = None
            if first_sku:
                updates['sku'] = first_sku
            if product_name:
                updates['product_name'] = product_name
            
            if updates:
                self.receipt_db.update_receipt(receipt_id, updates)
            
            # 保証書一覧テーブルを更新
            if hasattr(self, 'warranty_table') and table_row >= 0:
                self.warranty_table.blockSignals(True)
                
                # 日付列を更新
                if purchase_date_str:
                    date_item = self.warranty_table.item(table_row, 3)
                    if date_item:
                        date_item.setText(purchase_date_str)
                
                # 店舗コード列を更新
                if store_code_str:
                    store_code_item = self.warranty_table.item(table_row, 6)
                    if store_code_item:
                        # 店舗名を取得して表示ラベルを作成
                        store_name = store_name_combo.currentText() if store_name_combo else ''
                        store_label = self._format_store_code_label(store_code_str, store_name)
                        store_code_item.setText(store_label)
                        store_code_item.setData(Qt.UserRole, store_code_str)
                
                # 保証期間(日)列を更新
                days_item = self.warranty_table.item(table_row, 9)
                if days_item:
                    days_item.setText(str(warranty_days))
                else:
                    self.warranty_table.setItem(table_row, 9, QTableWidgetItem(str(warranty_days)))
                
                # 保証最終日列を更新
                warranty_until_widget = self.warranty_table.cellWidget(table_row, 10)
                if warranty_until_widget and isinstance(warranty_until_widget, QDateEdit):
                    warranty_until_widget.setDate(warranty_until)
                else:
                    # ウィジェットがない場合は新規作成
                    date_edit = QDateEdit()
                    date_edit.setCalendarPopup(True)
                    date_edit.setDate(warranty_until)
                    date_edit.dateChanged.connect(lambda qd, r=table_row: self.on_warranty_date_changed(r, qd))
                    self.warranty_table.setCellWidget(table_row, 10, date_edit)
                
                # 紐付けSKUを保証書一覧のSKU欄に入力（カンマ区切りで複数表示）
                if linked_skus:
                    # すべての紐付けSKUをカンマ区切りで表示
                    sku_display = ', '.join(linked_skus)
                    # SKU列を更新
                    sku_item = self.warranty_table.item(table_row, 7)
                    if sku_item:
                        sku_item.setText(sku_display)
                    else:
                        self.warranty_table.setItem(table_row, 7, QTableWidgetItem(sku_display))
                    
                    # 商品名列を更新（最初のSKUの商品名を表示）
                    product_item = self.warranty_table.item(table_row, 8)
                    if product_item:
                        product_item.setText(product_name)
                    else:
                        self.warranty_table.setItem(table_row, 8, QTableWidgetItem(product_name))
                    
                    # SKU/商品名セルにプルダウンを設定（既存のロジックを使用）
                    receipt_data = self.receipt_db.get_receipt(receipt_id)
                    if receipt_data:
                        # receipt_dataを更新（SKUと商品名を含める）
                        receipt_data = dict(receipt_data)
                        # 表示用にカンマ区切りのSKUを設定
                        receipt_data['sku'] = sku_display
                        receipt_data['product_name'] = product_name
                        self._populate_warranty_product_cell(table_row, receipt_data, sku_display, product_name)
                
                self.warranty_table.blockSignals(False)
            
            QMessageBox.information(self, "完了", "保証書情報を保存しました。")
            dialog.accept()
        except Exception as e:
            import traceback
            print(f"保証書編集保存エラー: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "エラー", f"保証書情報の保存に失敗しました:\n{e}")
    
    # ===== 保証書テーブルの編集 =====
    def on_warranty_cell_changed(self, row: int, column: int):
        """保証期間/店舗コード編集時の処理（保証最終日は on_warranty_date_changed で処理）"""
        # 列インデックス: 0=ID,1=種別,2=画像,3=レシートID,4=日付,5=店舗名,6=電話,7=店舗コード,8=SKU,9=商品名,10=保証期間,11=保証最終日
        # 店舗コード変更時は商品候補を更新
        if column == 7:
            id_item = self.warranty_table.item(row, 0)
            if not id_item:
                return
            try:
                receipt_id = int(id_item.text())
            except ValueError:
                return
            receipt = self.receipt_db.get_receipt(receipt_id)
            if not receipt:
                return
            # テーブル上の店舗コードを優先
            store_code_item = self.warranty_table.item(row, 6)
            if store_code_item:
                new_code = self._store_code_from_item(store_code_item)
                receipt = dict(receipt)
                receipt["store_code"] = new_code
                # 表示をコード+名称に整える
                display_label = self._format_store_code_label(new_code, receipt.get("store_name_raw") or "")
                self.warranty_table.blockSignals(True)
                store_code_item.setText(display_label)
                store_code_item.setData(Qt.UserRole, new_code)
                self.warranty_table.blockSignals(False)
            sku_item = self.warranty_table.item(row, 8)
            name_item = self.warranty_table.item(row, 9)
            current_sku = sku_item.text() if sku_item else ""
            current_name = name_item.text() if name_item else ""
            self._populate_warranty_product_cell(row, receipt, current_sku, current_name)
            return

        # 保証期間(日)列でなければ何もしない（列インデックス9）
        if column != 9:
            return
        if not hasattr(self, "warranty_table"):
            return
        id_item = self.warranty_table.item(row, 0)
        date_item = self.warranty_table.item(row, 3)  # 日付列（列インデックス3）
        days_item = self.warranty_table.item(row, 9)  # 保証期間(日)列（列インデックス9）
        if not id_item or not date_item or not days_item:
            return
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return
        purchase_date = date_item.text().strip()
        try:
            days = int(days_item.text().strip())
        except (ValueError, TypeError):
            return

        # 日付計算
        from datetime import datetime, timedelta

        # 日付文字列を正規化（yyyy-MM-dd 形式に揃える）
        normalized = purchase_date.replace("/", "-").split(" ")[0]
        try:
            base_date = datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError:
            # 日付形式不正の場合は何もしない
            return
        final_date = base_date + timedelta(days=days)
        final_str = final_date.strftime("%Y-%m-%d")

        # テーブル更新（再帰呼び出し防止のためシグナル一時停止）
        from PySide6.QtWidgets import QDateEdit

        self.warranty_table.blockSignals(True)
        widget = self.warranty_table.cellWidget(row, 10)  # 保証最終日列（列インデックス10）
        if isinstance(widget, QDateEdit):
            widget.setDate(QDate.fromString(final_str, "yyyy-MM-dd"))
        else:
            self.warranty_table.setItem(row, 10, QTableWidgetItem(final_str))
        self.warranty_table.blockSignals(False)

        # DB更新
        updates = {"warranty_days": days, "warranty_until": final_str}
        self.receipt_db.update_receipt(receipt_id, updates)

    def on_warranty_date_changed(self, row: int, qdate: QDate):
        """保証最終日を変更したときに保証期間(日)を逆算してDBに保存"""
        if not hasattr(self, "warranty_table"):
            return
        id_item = self.warranty_table.item(row, 0)
        date_item = self.warranty_table.item(row, 3)  # 日付列（列インデックス3）
        if not id_item or not date_item:
            return
        try:
            receipt_id = int(id_item.text())
        except ValueError:
            return

        purchase_date = date_item.text().strip()
        if not purchase_date:
            return

        from datetime import datetime

        # 日付文字列を正規化（yyyy-MM-dd 形式に揃える）
        normalized = purchase_date.replace("/", "-").split(" ")[0]
        try:
            base_date = datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError:
            return

        final_str = qdate.toString("yyyy-MM-dd")
        try:
            final_date = datetime.strptime(final_str, "%Y-%m-%d")
        except ValueError:
            return

        days = (final_date - base_date).days
        if days < 0:
            # マイナスはおかしいので何もしない
            return

        # テーブル更新（cellChanged を発火させないようにシグナルをブロック）
        self.warranty_table.blockSignals(True)
        self.warranty_table.setItem(row, 9, QTableWidgetItem(str(days)))  # 保証期間(日)列（列インデックス9）
        self.warranty_table.blockSignals(False)

        # DB更新
        updates = {"warranty_days": days, "warranty_until": final_str}
        self.receipt_db.update_receipt(receipt_id, updates)

    def _populate_warranty_product_cell(self, row: int, receipt: Dict[str, Any], sku: str, product_name: str):
        """
        保証書一覧の SKU / 商品名セルにプルダウンを設定し、選択した商品からSKUを自動入力
        """
        # 既存テキストをいったん設定（編集途中の値も保持）
        self.warranty_table.setItem(row, 7, QTableWidgetItem(sku))
        self.warranty_table.setItem(row, 8, QTableWidgetItem(product_name))

        # 候補取得：仕入DBの全レコードから、日付＋店舗コードが一致する商品を抽出
        candidates = []
        purchase_date_norm = self._normalize_purchase_date_text(receipt.get("purchase_date"))
        store_code_item = self.warranty_table.item(row, 6)
        store_code = (self._store_code_from_item(store_code_item) or receipt.get("store_code") or "").strip()
        if self.product_widget and hasattr(self.product_widget, "purchase_all_records") and purchase_date_norm and store_code:
            for rec in self.product_widget.purchase_all_records:
                rec_date = (
                    rec.get("仕入れ日")
                    or rec.get("purchase_date")
                    or rec.get("purchaseDate")
                    or rec.get("date")
                )
                rec_date_norm = self._normalize_purchase_date_text(rec_date)
                if not rec_date_norm or rec_date_norm != purchase_date_norm:
                    continue
                rec_store = (
                    rec.get("仕入先コード")
                    or rec.get("仕入先")
                    or rec.get("store_code")
                    or rec.get("店舗コード")
                    or rec.get("supplier_code")
                )
                rec_store = str(rec_store).strip() if rec_store else ""
                if rec_store != store_code:
                    continue
                cand_sku = rec.get("SKU") or rec.get("sku") or ""
                cand_name = rec.get("商品名") or rec.get("title") or ""
                if cand_name:
                    candidates.append((cand_sku, cand_name))

        # プルダウン(商品名)を作成
        combo = QComboBox()
        combo.addItem("（選択してください）", userData=None)
        combo.setMinimumWidth(180)
        # 重複除去
        seen = set()
        for cand_sku, cand_name in candidates:
            key = (cand_sku, cand_name)
            if key in seen:
                continue
            seen.add(key)
            combo.addItem(cand_name, userData={"sku": cand_sku, "name": cand_name})

        # 既存値があれば選択状態にする／候補にない場合は末尾に追加
        selected_index = 0
        if product_name:
            for idx in range(1, combo.count()):
                data = combo.itemData(idx)
                if data and data.get("name") == product_name:
                    selected_index = idx
                    break
            else:
                combo.addItem(product_name, userData={"sku": sku, "name": product_name})
                selected_index = combo.count() - 1
        combo.setCurrentIndex(selected_index)

        # 選択変更時の処理
        def on_combo_changed(index: int, table_row=row):
            data = combo.itemData(index)
            if not data:
                return
            new_sku = data.get("sku") or ""
            new_name = data.get("name") or ""
            id_item = self.warranty_table.item(table_row, 0)
            if not id_item:
                return
            try:
                rec_id = int(id_item.text())
            except ValueError:
                return
            # テーブル更新
            self.warranty_table.blockSignals(True)
            sku_item = self.warranty_table.item(table_row, 7)
            if sku_item:
                sku_item.setText(new_sku)
            else:
                self.warranty_table.setItem(table_row, 7, QTableWidgetItem(new_sku))
            name_item = self.warranty_table.item(table_row, 8)
            if name_item:
                name_item.setText(new_name)
            else:
                self.warranty_table.setItem(table_row, 8, QTableWidgetItem(new_name))
            self.warranty_table.blockSignals(False)
            # DB更新
            self.receipt_db.update_receipt(rec_id, {"sku": new_sku, "product_name": new_name})

        combo.currentIndexChanged.connect(on_combo_changed)
        self.warranty_table.setCellWidget(row, 8, combo)

